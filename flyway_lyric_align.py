"""
ComfyUI Flyway Plugin - Lyric Align
🐦‍🔥 Lyric Align -> LRC/SRT/ASS
(merged in from the former standalone `test-comfyui` plugin)

Known-lyrics alignment via the external `lyric-align` CLI, with a plain
faster-whisper transcription fallback (flyway_transcribe_only.py) when no
lyrics text is supplied.
"""
import os
import subprocess
import sys
import tempfile
import wave
import folder_paths

# Both locations are derived from the running ComfyUI install instead of a
# hard-coded drive path, so the plugin keeps working if the install moves.
CT2_CUDA12_DLL_DIR = os.path.join(folder_paths.base_path, "third_party", "faster-whisper-cuda12")
DEFAULT_ASR_MODEL = os.path.join(folder_paths.models_dir, "whisper", "lyric-align-large-v3-ct2")

try:
    import numpy as np
except ImportError:
    np = None


class LyricAlignLRC:
    """
    Wraps the `lyric-align` command-line tool to align known lyrics onto an
    audio clip and emit timestamped lyrics (LRC by default; SRT/VTT/ASS/TTML
    also supported).

    Install it once (outside ComfyUI, in its own isolated environment):

        pip install uv
        uv tool install "lyric-align[asr]"

    This node shells out to the `lyric-align` command, so it must be on the
    PATH of the process ComfyUI itself is running under. `uv tool install`
    normally puts it on your user PATH (e.g. %USERPROFILE%\\.local\\bin on
    Windows) — if ComfyUI was launched from a shell that doesn't see that
    PATH entry (common with the portable build's own launch scripts), open
    a normal terminal, run `lyric-align --version` to confirm it resolves
    there, then start ComfyUI from that same terminal.

    Inputs:
      - audio: ComfyUI AUDIO (e.g. straight out of a music-gen node)
      - lyrics_text: plain text, one lyric line per line. Blank lines,
        "# comments" and section markers like [Verse 1] / [Hook] are
        skipped, so a pasted lyric sheet works as-is.
      - language: BCP-47-ish code, e.g. "zh", "ja", "en". CJK languages get
        a lower, script-aware match threshold automatically.
      - no_vad: turn off the voice-activity filter. Needed for slow,
        sustained singing (ballads, hymns) where held notes get mistaken
        for silence and the whole line goes unmatched.
      - interpolate: fill in lines that couldn't be confidently matched
        instead of leaving them blank (still flagged as guessed inside the
        file itself where the format supports it).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "lyrics_text": ("STRING", {"multiline": True, "default": ""}),
                "language": ("STRING", {"default": "zh"}),
                "asr_model": ("STRING", {"default": DEFAULT_ASR_MODEL, "tooltip": "faster-whisper model name, or a local CTranslate2 model directory"}),
                "asr_device": (["cpu", "cuda"], {"default": "cpu"}),
                "output_format": (
                    ["lrc", "elrc", "srt", "vtt", "ass", "ttml"],
                    {"default": "lrc"},
                ),
            },
            "optional": {
                "no_vad": ("BOOLEAN", {"default": False}),
                "karaoke": ("BOOLEAN", {"default": False}),
                "interpolate": ("BOOLEAN", {"default": False}),
                "save_lyrics": ("BOOLEAN", {"default": True}),
                "free_vram_first": ("BOOLEAN", {"default": True, "tooltip": "Unload ComfyUI's own models and empty the CUDA cache before starting the lyric-align subprocess, so it initializes its own CUDA context on uncontended VRAM. Only matters when asr_device is cuda."}),
                "output_dir": ("STRING", {"default": ""}),
                "filename_prefix": ("STRING", {"default": "lyric_align_out"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("aligned_text", "output_path")
    FUNCTION = "run"
    CATEGORY = "flyway"

    def _save_audio_to_wav(self, audio, path):
        """ComfyUI's AUDIO type is {"waveform": tensor[B,C,T], "sample_rate": int}."""
        waveform = audio["waveform"]
        sample_rate = int(audio["sample_rate"])

        wf = waveform[0]
        if hasattr(wf, "detach"):
            wf = wf.detach().cpu().numpy()

        wf = np.clip(wf, -1.0, 1.0)
        wf_int16 = (wf * 32767.0).astype(np.int16)
        if wf_int16.ndim == 1:
            wf_int16 = wf_int16[None, :]

        channels = wf_int16.shape[0]
        interleaved = wf_int16.T.reshape(-1)

        with wave.open(path, "wb") as wf_file:
            wf_file.setnchannels(channels)
            wf_file.setsampwidth(2)
            wf_file.setframerate(sample_rate)
            wf_file.writeframes(interleaved.tobytes())

    def run(
        self,
        audio,
        lyrics_text,
        language,
        asr_model,
        asr_device,
        output_format,
        no_vad=False,
        karaoke=False,
        interpolate=False,
        save_lyrics=True,
        free_vram_first=True,
        output_dir="",
        filename_prefix="lyric_align_out",
    ):
        if np is None:
            raise RuntimeError(
                "numpy is required by LyricAlignLRC but could not be imported "
                "in this Python environment."
            )

        work_dir = tempfile.mkdtemp(prefix="lyric_align_")
        if save_lyrics:
            save_dir = output_dir.strip() or os.path.join(folder_paths.get_output_directory(), "audio")
            os.makedirs(save_dir, exist_ok=True)
            out_path = os.path.join(save_dir, f"{filename_prefix}.{output_format}")
        else:
            out_path = os.path.join(work_dir, f"{filename_prefix}.{output_format}")

        wav_path = os.path.join(work_dir, f"{filename_prefix}.wav")
        lyrics_path = os.path.join(work_dir, f"{filename_prefix}.lyrics.txt")

        self._save_audio_to_wav(audio, wav_path)

        child_env = os.environ.copy()
        if os.path.isdir(CT2_CUDA12_DLL_DIR):
            child_env["PATH"] = CT2_CUDA12_DLL_DIR + os.pathsep + child_env.get("PATH", "")
        child_env["PYTHONUTF8"] = "1"

        if free_vram_first and asr_device == "cuda":
            # A crash was traced to ctranslate2's CUDA backend initializing
            # while ComfyUI's own torch models were still holding a large,
            # possibly fragmented chunk of VRAM. Give the subprocess a clean
            # slate before it opens its own CUDA context. Best-effort: never
            # let a failure here block the actual alignment.
            try:
                import comfy.model_management as _mm
                _mm.unload_all_models()
                _mm.soft_empty_cache()
            except Exception:
                pass

        if not lyrics_text.strip():
            # No known lyrics supplied -> plain ASR transcript + timestamps
            # instead of lyric-align's known-lyrics alignment. lyric-align
            # itself has no "no lyrics" mode (the lyrics argument is
            # required), so this runs faster-whisper directly via a small
            # sibling script, in the same subprocess/env isolation.
            helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flyway_transcribe_only.py")
            py_exe = sys.executable
            cmd = [
                py_exe, helper, wav_path, asr_model.strip() or "medium", asr_device,
                language or "", "1" if no_vad else "0", output_format, out_path,
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=1800, env=child_env
                )
            except FileNotFoundError:
                raise RuntimeError(f"Could not find Python interpreter at {py_exe} to run flyway_transcribe_only.py.")

            if result.returncode != 0:
                raise RuntimeError(
                    f"flyway_transcribe_only.py exited with code {result.returncode}.\n"
                    f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
                )

            aligned_text = ""
            if os.path.exists(out_path):
                with open(out_path, "r", encoding="utf-8") as f:
                    aligned_text = f.read()
            return (aligned_text, out_path)

        with open(lyrics_path, "w", encoding="utf-8") as f:
            f.write(lyrics_text)

        cmd = ["lyric-align", wav_path, lyrics_path, "-f", output_format, "-o", out_path]
        if asr_model.strip():
            cmd += ["--model", asr_model.strip()]
        cmd += ["--device", asr_device]
        if language:
            cmd += ["--language", language]
        if no_vad:
            cmd.append("--no-vad")
        if karaoke:
            cmd.append("--karaoke")
        if interpolate:
            cmd.append("--interpolate")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=1800, env=child_env
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Could not find the `lyric-align` command on PATH. Install it "
                'with `uv tool install "lyric-align[asr]"` and make sure the '
                "shell/process ComfyUI is running under can see it "
                "(`lyric-align --version` should work there)."
            )

        if result.returncode != 0:
            raise RuntimeError(
                f"lyric-align exited with code {result.returncode}.\n"
                f"--- stdout ---\n{result.stdout}\n"
                f"--- stderr ---\n{result.stderr}"
            )

        aligned_text = ""
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                aligned_text = f.read()

        return (aligned_text, out_path)


NODE_CLASS_MAPPINGS = {
    "LyricAlignLRC": LyricAlignLRC,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LyricAlignLRC": "🐦‍🔥 Lyric Align -> LRC/SRT/ASS",
}
