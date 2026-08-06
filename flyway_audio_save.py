"""
ComfyUI Flyway Plugin - Audio Save Node
🐦‍🔥 Audio Save
deps: pip install soundfile pydub  (lossy formats also need ffmpeg)
"""

import os
import re
import datetime
import numpy as np
import folder_paths

# ── format config ─────────────────────────────────────────────────────────────
FORMAT_CONFIG = {
    "wav":  {"ext": "wav",  "lossless": True},
    "flac": {"ext": "flac", "lossless": True},
    "mp3":  {"ext": "mp3",  "lossless": False},
    "aac":  {"ext": "aac",  "lossless": False},
    "ogg":  {"ext": "ogg",  "lossless": False},
    "m4a":  {"ext": "m4a",  "lossless": False},
    "opus": {"ext": "opus", "lossless": False},
}

FORMAT_KEYS = list(FORMAT_CONFIG.keys())

LOSSY_QUALITY =["default", "320k", "256k", "192k", "128k", "96k", "64k",
                 "q9 (best)", "q7 (high)", "q5 (mid)", "q3 (low)"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_prefix(prefix: str, ext: str):
    prefix = prefix.strip().replace("\\", "/")
    prefix = re.sub(r'\.[a-zA-Z0-9]+$', '', prefix)
    if "/" in prefix:
        sub, stem = prefix.rsplit("/", 1)
        return sub.strip("/"), stem or "output"
    return "", prefix or "output"


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip() or "output"


def _unique(directory: str, stem: str, ext: str) -> str:
    p = os.path.join(directory, f"{stem}.{ext}")
    if not os.path.exists(p):
        return p
    i = 1
    while True:
        p = os.path.join(directory, f"{stem}_{i:04d}.{ext}")
        if not os.path.exists(p):
            return p
        i += 1


def _to_numpy(audio, default_sr=44100):
    import torch
    sr = default_sr
    waveform = audio
    if isinstance(audio, dict):
        sr = audio.get("sample_rate", default_sr)
        waveform = audio["waveform"]
    if isinstance(waveform, torch.Tensor):
        waveform = waveform.cpu().float().numpy()
    if waveform.ndim == 3:
        waveform = waveform[0]
    if waveform.ndim == 2:
        waveform = waveform.T
    elif waveform.ndim == 1:
        waveform = waveform[:, np.newaxis]
    return waveform.astype(np.float32), int(sr)


def _write(waveform_np, sr, out_path, fmt_key, quality):
    ext = FORMAT_CONFIG[fmt_key]["ext"]

    if ext in ("wav", "flac"):
        try:
            import soundfile as sf
            sf.write(out_path, waveform_np, sr,
                     subtype="PCM_24" if ext == "wav" else None)
            return out_path
        except ImportError:
            pass

    try:
        from pydub import AudioSegment
        pcm = (waveform_np * 32767).clip(-32768, 32767).astype(np.int16)
        channels = pcm.shape[1] if pcm.ndim == 2 else 1
        seg = AudioSegment(data=pcm.tobytes(), sample_width=2,
                           frame_rate=sr, channels=channels)
        bk = quality if (quality and quality.endswith("k")) else "192k"
        kw = {
            "wav":  {"format": "wav"},
            "flac": {"format": "flac"},
            "mp3":  {"format": "mp3",  "bitrate": bk},
            "aac":  {"format": "adts", "bitrate": bk, "codec": "aac"},
            "m4a":  {"format": "mp4",  "bitrate": bk, "codec": "aac"},
            "ogg":  {"format": "ogg",  "codec": "libvorbis",
                     "parameters":["-q:a", {
                         "q9 (best)": "9", "q7 (high)": "7",
                         "q5 (mid)":  "5", "q3 (low)":  "3",
                     }.get(quality, "7")]},
            "opus": {"format": "opus", "bitrate": bk},
        }[ext]
        seg.export(out_path, **kw)
        return out_path
    except ImportError:
        raise RuntimeError(
            "Missing deps: pip install soundfile pydub\n"
            "Lossy formats also need ffmpeg."
        )


def _ui_audio(filepath: str, output_root: str, file_type: str) -> dict:
    """
    Build ComfyUI ui.audio dict.
    注意：这里必须严格匹配官方的返回格式。
    """
    filename = os.path.basename(filepath)
    subfolder = os.path.dirname(filepath).replace(output_root, "").strip("\\/")
    
    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": file_type,
    }


# ── node ──────────────────────────────────────────────────────────────────────

class FlywayAudioSave:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "save_file": ("BOOLEAN", {
                    "default":   False,
                    "label_on":  "Save",
                    "label_off": "Preview only",
                }),
                "format": (FORMAT_KEYS, {"default": "wav"}),
                "quality": (LOSSY_QUALITY, {"default": "default"}),
                "filename_prefix": ("STRING", {
                    "default":   "audio/output",
                    "multiline": False,
                }),
            },
        }

    RETURN_TYPES  = ("STRING", "STRING")
    RETURN_NAMES  = ("filepath", "filename")
    FUNCTION      = "save"
    CATEGORY      = "flyway"
    OUTPUT_NODE   = True

    def save(self, audio, save_file, format, quality, filename_prefix):
        waveform_np, sr = _to_numpy(audio)
        cfg = FORMAT_CONFIG[format]
        ext = cfg["ext"]
        eff_quality = "default" if cfg["lossless"] else quality
        channels = waveform_np.shape[1] if waveform_np.ndim == 2 else 1
        output_root = folder_paths.get_output_directory()

        subfolder, stem = _parse_prefix(filename_prefix, ext)

        # ── Preview only ──────────────────────────────────────────────────────
        if not save_file:
            tmp_root = folder_paths.get_temp_directory()
            os.makedirs(tmp_root, exist_ok=True)
            tmp_path = _unique(tmp_root, "flyway_preview", ext)
            saved = _write(waveform_np, sr, tmp_path, format, eff_quality)
            fname = os.path.basename(saved)
            print(f"[Flyway] AudioSave preview | {format} | {sr}Hz {channels}ch")
            
            # 返回结构必须包含 ui 字典
            return {
                "ui": {"audio": [_ui_audio(saved, tmp_root, "temp")]},
                "result": ("", fname),
            }

        # ── Save to disk ──────────────────────────────────────────────────────
        save_dir = os.path.abspath(
            os.path.join(output_root, subfolder) if subfolder
            else output_root
        )
        os.makedirs(save_dir, exist_ok=True)

        out_path = _unique(save_dir, _safe(stem), ext)
        saved    = _write(waveform_np, sr, out_path, format, eff_quality)
        fname    = os.path.basename(saved)
        size_kb  = os.path.getsize(saved) / 1024

        print(f"[Flyway] AudioSave -> {saved} | "
              f"{format} {eff_quality} | {size_kb:.1f}KB | {sr}Hz {channels}ch")

        return {
            "ui": {"audio":[_ui_audio(saved, output_root, "output")]},
            "result": (saved, fname),
        }


# ── register ──────────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlywayAudioSave": FlywayAudioSave,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywayAudioSave": "🐦‍🔥 Audio Save",
}