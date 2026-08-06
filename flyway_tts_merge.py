"""
ComfyUI Flyway Plugin - TTS Merge Node  v2.0
🐦‍🔥 TTS Merge

Reads a translated SRT subtitle, generates TTS audio for every sentence via
FishAudioS2 (loaded from ComfyUI's global NODE_CLASS_MAPPINGS), then aligns
each clip to the original timestamp slot and assembles the final audio track.

Optional background audio can be mixed in at the end.

per_segment_json (optional STRING):
  JSON array to override speed / volume per sentence index (1-based).
  Example: [{"index": 3, "speed": 1.15}, {"index": 7, "volume": 0.6}]

overflow_mode:
  stretch  – time-stretch TTS to fit the subtitle slot (default)
  trim     – truncate TTS at slot end
  overflow – place TTS as-is, may overlap next slot
"""

import os
import re
import sys
import json
import torch
import numpy as np
import folder_paths

# ── SRT parser ────────────────────────────────────────────────────────────────

def parse_subtitle(subtitle: str) -> list[dict]:
    ts_re = re.compile(
        r'(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})'
    )

    def t2s(t: str) -> float:
        t = t.replace(",", ".")
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    segs, i = [], 0
    lines   = subtitle.splitlines()
    idx     = 0
    while i < len(lines):
        line = lines[i].strip()
        m    = ts_re.match(line)
        if m:
            idx  += 1
            start = t2s(m.group(1))
            end   = t2s(m.group(2))
            i    += 1
            parts = []
            while i < len(lines) and lines[i].strip():
                tl = lines[i].strip()
                if not re.match(r'^\d+$', tl):
                    parts.append(tl)
                i += 1
            segs.append({
                "index": idx,
                "start": start,
                "end":   end,
                "text":  " ".join(parts).strip(),
            })
        else:
            i += 1
    return segs

# ── checkpoint discovery ──────────────────────────────────────────────────────

def _find_fish_checkpoints() -> list[str]:
    """
    Scan custom_nodes for a FishAudioS2 plugin directory and list its checkpoints.
    Returns relative paths like ["checkpoints/s2-pro", ...].
    """
    cn = os.path.join(folder_paths.base_path, "custom_nodes")
    plugin_dir = None
    try:
        for entry in os.listdir(cn):
            if "fishaudios2" in entry.lower():
                plugin_dir = os.path.join(cn, entry)
                break
    except Exception:
        pass

    if not plugin_dir:
        return ["checkpoints/s2-pro"]

    ckpt_root = os.path.join(plugin_dir, "checkpoints")
    ckpts = []
    if os.path.exists(ckpt_root):
        for d in os.listdir(ckpt_root):
            if os.path.isdir(os.path.join(ckpt_root, d)):
                ckpts.append(f"checkpoints/{d}")
    return sorted(ckpts) or ["checkpoints/s2-pro"]

# ── FishAudioS2 access via ComfyUI global registry ───────────────────────────

def _get_fish_class(with_ref_audio: bool):
    """
    Retrieve FishAudioS2 TTS class from ComfyUI's NODE_CLASS_MAPPINGS.
    Prefers voice-clone variant when ref_audio is provided.
    Raises RuntimeError with a clear message if not found.
    """
    try:
        from nodes import NODE_CLASS_MAPPINGS
    except ImportError as e:
        raise RuntimeError(
            "[Flyway] Cannot import ComfyUI nodes. "
            "Make sure this plugin runs inside ComfyUI."
        ) from e

    preferred = "FishS2VoiceCloneTTS" if with_ref_audio else "FishS2TTS"
    fallback  = "FishS2TTS"           if with_ref_audio else None

    cls = NODE_CLASS_MAPPINGS.get(preferred)
    if cls is None and fallback:
        cls = NODE_CLASS_MAPPINGS.get(fallback)
    if cls is None:
        # Last resort: fuzzy match
        for key, val in NODE_CLASS_MAPPINGS.items():
            if "fishs2" in key.lower() or "fish_s2" in key.lower():
                cls = val
                break
    if cls is None:
        raise RuntimeError(
            "[Flyway] FishAudioS2 node not found in NODE_CLASS_MAPPINGS. "
            "Please install and enable the FishAudioS2 ComfyUI plugin."
        )
    return cls

# ── audio helpers ─────────────────────────────────────────────────────────────

def _to_numpy(audio) -> tuple[np.ndarray | None, int]:
    if audio is None:
        return None, 44100
    if isinstance(audio, dict):
        sr  = int(audio.get("sample_rate", 44100))
        wav = audio["waveform"]
    else:
        return None, 44100

    if isinstance(wav, torch.Tensor):
        wav = wav.cpu().float().numpy()
    if wav.ndim == 3:
        wav = wav[0]                    # (batch, ch, samples) → (ch, samples)
    if wav.ndim == 2:
        wav = wav.T                     # (ch, samples) → (samples, ch)
    elif wav.ndim == 1:
        wav = wav[:, np.newaxis]        # mono → (samples, 1)
    return wav.astype(np.float32), sr

def _resample(wav: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr:
        return wav
    try:
        import librosa
        # wav shape: (samples, ch)
        out_chs = []
        for ch in range(wav.shape[1]):
            out_chs.append(
                librosa.resample(wav[:, ch], orig_sr=src_sr, target_sr=dst_sr)
            )
        return np.stack(out_chs, axis=1).astype(np.float32)
    except ImportError:
        # Fallback: nearest-neighbour (low quality but dependency-free)
        ratio   = dst_sr / src_sr
        new_len = max(1, int(round(wav.shape[0] * ratio)))
        indices = (np.arange(new_len) / ratio).astype(int).clip(0, wav.shape[0] - 1)
        return wav[indices]

def _time_stretch(wav: np.ndarray, sr: int, target_dur: float) -> np.ndarray:
    """Stretch / compress wav to exactly target_dur seconds."""
    src_dur = wav.shape[0] / sr
    if src_dur <= 0 or abs(src_dur - target_dur) < 0.01:
        return wav
    rate = src_dur / target_dur
    try:
        import librosa
        out_chs = []
        for ch in range(wav.shape[1]):
            out_chs.append(librosa.effects.time_stretch(wav[:, ch], rate=rate))
        stretched = np.stack(out_chs, axis=1).astype(np.float32)
    except ImportError:
        # No librosa: crude nearest-neighbour resample as proxy
        stretched = _resample(wav, sr, int(sr / rate))
    # Hard-trim to exact target length
    target_samples = int(round(target_dur * sr))
    if stretched.shape[0] >= target_samples:
        return stretched[:target_samples]
    # Pad with silence if stretch left us short
    pad = np.zeros((target_samples - stretched.shape[0], wav.shape[1]), dtype=np.float32)
    return np.concatenate([stretched, pad], axis=0)

# ── per-segment override parser ───────────────────────────────────────────────

def _parse_segment_overrides(json_str: str) -> dict[int, dict]:
    """
    Parse per_segment_json into {index: {speed, volume}} dict.
    Returns empty dict on any parse error.
    """
    if not json_str or not json_str.strip():
        return {}
    try:
        items = json.loads(json_str.strip())
        result = {}
        for item in items:
            idx = int(item.get("index", -1))
            if idx < 1:
                continue
            result[idx] = {
                "speed":  float(item.get("speed",  1.0)),
                "volume": float(item.get("volume", 1.0)),
            }
        return result
    except Exception as e:
        print(f"[Flyway] TTSMerge: per_segment_json parse error — {e}")
        return {}

# ── main node ─────────────────────────────────────────────────────────────────

class FlywayTTSMerge:

    OVERFLOW_OPTIONS = ["stretch", "trim", "overflow"]
    _ckpts = _find_fish_checkpoints()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "translated_subtitle": ("STRING", {"multiline": True, "default": ""}),
                "checkpoint": (cls._ckpts, {"default": cls._ckpts[0]}),
                "precision":  (["float32", "half", "bfloat16"], {"default": "half"}),
                "compile":    ("BOOLEAN", {
                    "default":   False,
                    "label_on":  "Compile (fastest)",
                    "label_off": "Normal",
                }),
                "seed": ("INT", {
                    "default": 42, "min": 0,
                    "max":     0xffffffffffffffff,
                }),
                # Alignment strategy
                "overflow_mode": (cls.OVERFLOW_OPTIONS, {"default": "stretch"}),
                # Default TTS output volume (can be overridden per segment)
                "tts_volume": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05,
                }),
            },
            "optional": {
                # FishAudioS2 voice-clone inputs
                "ref_audio":   ("AUDIO",),
                "ref_text":    ("STRING", {"multiline": True, "default": ""}),
                # Background audio
                "bg_audio":    ("AUDIO",),
                "mix_background": ("BOOLEAN", {
                    "default":  False,
                    "label_on": "Mix BG",
                    "label_off": "TTS only",
                }),
                "bg_volume": ("FLOAT", {
                    "default": 0.4, "min": 0.0, "max": 2.0, "step": 0.05,
                }),
                # Per-segment speed / volume overrides
                # Format: [{"index": 1, "speed": 1.2}, {"index": 3, "volume": 0.8}]
                "per_segment_json": ("STRING", {
                    "multiline": True,
                    "default":   "",
                }),
            },
        }

    RETURN_TYPES  = ("AUDIO", "STRING")
    RETURN_NAMES  = ("audio", "report")
    FUNCTION      = "generate"
    CATEGORY      = "flyway"

    def generate(
        self,
        translated_subtitle,
        checkpoint,
        precision,
        compile,
        seed,
        overflow_mode,
        tts_volume,
        ref_audio       = None,
        ref_text        = "",
        bg_audio        = None,
        mix_background  = False,
        bg_volume       = 0.4,
        per_segment_json = "",
    ):
        # ── parse subtitle ────────────────────────────────────────────────────
        segs = parse_subtitle(translated_subtitle)
        if not segs:
            raise ValueError("[Flyway] TTSMerge: subtitle parse returned 0 segments")

        # ── parse per-segment overrides ───────────────────────────────────────
        overrides = _parse_segment_overrides(per_segment_json)

        # ── resolve FishAudioS2 class ─────────────────────────────────────────
        fish_class    = _get_fish_class(with_ref_audio=ref_audio is not None)
        fish_instance = fish_class()
        fish_fn       = getattr(fish_instance, fish_class.FUNCTION)
        input_defs    = fish_class.INPUT_TYPES()["required"]

        print(f"[Flyway] TTSMerge: {len(segs)} segments | "
              f"fish={fish_class.__name__} | overflow={overflow_mode}")

        # ── prepare output buffer ─────────────────────────────────────────────
        bg_wav, bg_sr = _to_numpy(bg_audio)
        output_sr     = bg_sr if bg_wav is not None else 44100

        total_dur = (
            bg_wav.shape[0] / output_sr
            if bg_wav is not None
            else segs[-1]["end"] + 1.0
        )
        final_buf = np.zeros((int(total_dur * output_sr), 1), dtype=np.float32)

        # ── generate TTS per segment ──────────────────────────────────────────
        report_lines = [
            "🐦‍🔥 TTS Merge Report",
            f"   segments : {len(segs)}",
            f"   overflow : {overflow_mode}",
            f"   fish_cls : {fish_class.__name__}",
            "─" * 48,
        ]
        ok_count   = 0
        fail_count = 0

        for seg in segs:
            text = seg["text"].strip()
            if not text:
                report_lines.append(f"[{seg['index']:02d}/{len(segs):02d}] SKIP (empty)")
                continue

            ovr       = overrides.get(seg["index"], {})
            seg_vol   = ovr.get("volume", tts_volume)
            seg_speed = ovr.get("speed",  1.0)          # applied via stretch ratio

            slot_dur  = seg["end"] - seg["start"]
            if slot_dur <= 0:
                slot_dur = 1.0

            print(f"[Flyway] TTSMerge [{seg['index']:02d}/{len(segs):02d}] "
                  f"{seg['start']:.2f}s-{seg['end']:.2f}s  \"{text[:60]}\"")

            # Build kwargs for FishAudioS2
            kwargs: dict = {}
            for k in input_defs:
                kl = k.lower()
                if "text" in kl and "ref" not in kl:
                    kwargs[k] = text
                elif "checkpoint" in kl or "model" in kl:
                    kwargs[k] = checkpoint
                elif "precision" in kl:
                    kwargs[k] = precision
                elif "compile" in kl:
                    kwargs[k] = compile
                elif "seed" in kl:
                    kwargs[k] = seed
                elif "ref_text" in kl:
                    kwargs[k] = ref_text
                elif ("ref_audio" in kl or ("audio" in kl and "ref" in kl)) \
                        and ref_audio is not None:
                    kwargs[k] = ref_audio

            try:
                ret     = fish_fn(**kwargs)
                tts_wav, tts_sr = _to_numpy(ret[0] if isinstance(ret, (list, tuple)) else ret)
                if tts_wav is None:
                    raise ValueError("FishAudioS2 returned None waveform")

                # Resample to output SR
                if tts_sr != output_sr:
                    tts_wav = _resample(tts_wav, tts_sr, output_sr)

                tts_dur = tts_wav.shape[0] / output_sr

                # Apply per-segment speed as an extra stretch factor
                if abs(seg_speed - 1.0) > 0.01:
                    target = tts_dur / seg_speed
                    tts_wav = _time_stretch(tts_wav, output_sr, target)
                    tts_dur = tts_wav.shape[0] / output_sr

                # Align to slot
                if overflow_mode == "stretch":
                    tts_wav = _time_stretch(tts_wav, output_sr, slot_dur)
                elif overflow_mode == "trim":
                    max_samples = int(slot_dur * output_sr)
                    tts_wav = tts_wav[:max_samples]
                # "overflow": place as-is

                # Mix into buffer
                start_s = int(seg["start"] * output_sr)
                end_s   = start_s + tts_wav.shape[0]

                # Expand buffer if needed (overflow mode)
                if end_s > final_buf.shape[0]:
                    extra = np.zeros(
                        (end_s - final_buf.shape[0], final_buf.shape[1]),
                        dtype=np.float32,
                    )
                    final_buf = np.concatenate([final_buf, extra], axis=0)

                # Match channels
                if tts_wav.shape[1] < final_buf.shape[1]:
                    tts_wav = np.tile(tts_wav, (1, final_buf.shape[1]))
                elif tts_wav.shape[1] > final_buf.shape[1]:
                    final_buf = np.tile(final_buf, (1, tts_wav.shape[1]))

                final_buf[start_s:end_s] += tts_wav * seg_vol

                actual_dur = tts_wav.shape[0] / output_sr
                ovr_tag    = f" [speed×{seg_speed}]" if abs(seg_speed - 1.0) > 0.01 else ""
                ovr_tag   += f" [vol×{seg_vol}]"      if abs(seg_vol   - 1.0) > 0.01 else ""
                print(f"[Flyway] TTSMerge [{seg['index']:02d}] "
                      f"→ generated {tts_dur:.2f}s → placed {actual_dur:.2f}s{ovr_tag}")
                report_lines.append(
                    f"[{seg['index']:02d}] {seg['start']:.1f}-{seg['end']:.1f}s | "
                    f"gen={tts_dur:.2f}s{ovr_tag} ✓"
                )
                ok_count += 1

            except Exception as e:
                print(f"[Flyway] TTSMerge [{seg['index']:02d}] ERROR: {e}")
                report_lines.append(f"[{seg['index']:02d}] ERROR: {e}")
                fail_count += 1

        # ── mix background audio ──────────────────────────────────────────────
        if mix_background and bg_wav is not None:
            # Match channels
            if bg_wav.shape[1] > final_buf.shape[1]:
                final_buf = np.tile(final_buf, (1, bg_wav.shape[1]))
            elif bg_wav.shape[1] < final_buf.shape[1]:
                bg_wav = np.tile(bg_wav, (1, final_buf.shape[1]))
            # Resample BG if needed (already at output_sr but safety check)
            if bg_sr != output_sr:
                bg_wav = _resample(bg_wav, bg_sr, output_sr)

            min_len = min(final_buf.shape[0], bg_wav.shape[0])
            final_buf[:min_len] += bg_wav[:min_len] * bg_volume
            report_lines.append(f"[BG] mixed {min_len/output_sr:.1f}s at vol={bg_volume}")

        # ── normalise ─────────────────────────────────────────────────────────
        peak = np.abs(final_buf).max()
        if peak > 1.0:
            final_buf /= peak

        # ── build output AUDIO dict ───────────────────────────────────────────
        # ComfyUI AUDIO format: {"waveform": Tensor(1, ch, samples), "sample_rate": int}
        waveform   = torch.from_numpy(final_buf.T).unsqueeze(0).float()
        out_audio  = {"waveform": waveform, "sample_rate": output_sr}

        report_lines += [
            "─" * 48,
            f"Total : {ok_count} ok, {fail_count} failed",
            f"Output: {final_buf.shape[0]/output_sr:.2f}s  {final_buf.shape[1]}ch  {output_sr}Hz",
        ]
        report = "\n".join(report_lines)
        print(f"[Flyway] TTSMerge: done — {ok_count}/{len(segs)} segments OK")
        return (out_audio, report)


# ── register ──────────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlywayTTSMerge": FlywayTTSMerge,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywayTTSMerge": "🐦‍🔥 TTS Merge",
}