"""
ComfyUI Flyway Plugin - Audio Save Node
🐦‍🔥 音频保存 - 将音频保存为常见格式
安装: 复制到 ComfyUI/custom_nodes/comfyui-flyway/ 目录下
依赖: pip install soundfile pydub
"""

import os
import re
import datetime
import numpy as np
import folder_paths

# ── 格式配置表 ────────────────────────────────────────────────────────────────
# 结构: format_key -> { ext, lossless, quality_options, default_quality }
FORMAT_CONFIG = {
    "wav (无损)": {
        "ext": "wav",
        "lossless": True,
        "quality_options": ["无损 (原样)"],
        "default_quality": "无损 (原样)",
    },
    "flac (无损)": {
        "ext": "flac",
        "lossless": True,
        "quality_options": ["无损 (原样)"],
        "default_quality": "无损 (原样)",
    },
    "mp3": {
        "ext": "mp3",
        "lossless": False,
        "quality_options": ["320k", "256k", "192k", "128k", "96k"],
        "default_quality": "192k",
    },
    "aac": {
        "ext": "aac",
        "lossless": False,
        "quality_options": ["256k", "192k", "128k", "96k"],
        "default_quality": "192k",
    },
    "ogg": {
        "ext": "ogg",
        "lossless": False,
        "quality_options": ["高 (q=9)", "中高 (q=7)", "中 (q=5)", "低 (q=3)"],
        "default_quality": "中高 (q=7)",
    },
    "m4a": {
        "ext": "m4a",
        "lossless": False,
        "quality_options": ["256k", "192k", "128k", "96k"],
        "default_quality": "192k",
    },
    "opus": {
        "ext": "opus",
        "lossless": False,
        "quality_options": ["256k", "128k", "96k", "64k"],
        "default_quality": "128k",
    },
}

FORMAT_KEYS = list(FORMAT_CONFIG.keys())
DEFAULT_FORMAT = "wav (无损)"

# 所有质量选项的并集（供 INPUT_TYPES 静态声明用）
ALL_QUALITY_OPTIONS = ["无损 (原样)", "320k", "256k", "192k", "128k", "96k",
                       "高 (q=9)", "中高 (q=7)", "中 (q=5)", "低 (q=3)", "64k"]


# ── 辅助：安全文件名 ──────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """移除文件名中的非法字符"""
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name or "audio"


# ── 辅助：获取不冲突的输出路径 ───────────────────────────────────────────────

def _unique_path(directory: str, stem: str, ext: str) -> str:
    candidate = os.path.join(directory, f"{stem}.{ext}")
    if not os.path.exists(candidate):
        return candidate
    i = 1
    while True:
        candidate = os.path.join(directory, f"{stem}_{i:04d}.{ext}")
        if not os.path.exists(candidate):
            return candidate
        i += 1


# ── 辅助：audio tensor → numpy ───────────────────────────────────────────────

def _tensor_to_numpy(audio_tensor, sample_rate: int):
    """
    ComfyUI AUDIO 类型: dict {"waveform": Tensor, "sample_rate": int}
    waveform shape: (batch, channels, samples) 或 (channels, samples)
    返回 numpy (samples, channels) float32，范围 [-1, 1]
    """
    import torch
    waveform = audio_tensor

    # 兼容 dict 格式
    if isinstance(waveform, dict):
        sample_rate = waveform.get("sample_rate", sample_rate)
        waveform = waveform["waveform"]

    if isinstance(waveform, torch.Tensor):
        waveform = waveform.cpu().float().numpy()

    # 处理 batch 维度 (batch, ch, samples) → 取第一条
    if waveform.ndim == 3:
        waveform = waveform[0]

    # (channels, samples) → (samples, channels)
    if waveform.ndim == 2:
        waveform = waveform.T
    elif waveform.ndim == 1:
        waveform = waveform[:, np.newaxis]

    return waveform.astype(np.float32), sample_rate


# ── 核心保存函数 ──────────────────────────────────────────────────────────────

def _save_audio(waveform_np: np.ndarray, sample_rate: int,
                out_path: str, fmt_key: str, quality: str) -> str:
    """
    保存音频到 out_path。
    优先用 soundfile（无损/wav/flac），有损格式回落到 pydub+ffmpeg。
    返回实际保存路径。
    """
    cfg = FORMAT_CONFIG[fmt_key]
    ext = cfg["ext"]

    # ── WAV / FLAC：用 soundfile ──────────────────────────────────────────────
    if ext in ("wav", "flac"):
        try:
            import soundfile as sf
            subtype = "PCM_24" if ext == "wav" else None
            sf.write(out_path, waveform_np, sample_rate, subtype=subtype)
            return out_path
        except ImportError:
            pass  # 降级到 pydub

    # ── 有损格式：用 pydub ────────────────────────────────────────────────────
    try:
        from pydub import AudioSegment

        # numpy float32 [-1,1] → int16
        pcm = (waveform_np * 32767).clip(-32768, 32767).astype(np.int16)
        channels = pcm.shape[1] if pcm.ndim == 2 else 1
        raw = pcm.tobytes()

        seg = AudioSegment(
            data=raw,
            sample_width=2,
            frame_rate=sample_rate,
            channels=channels,
        )

        export_kwargs = {}

        if ext == "mp3":
            bitrate = quality if quality.endswith("k") else "192k"
            export_kwargs = {"format": "mp3", "bitrate": bitrate}

        elif ext == "flac":
            export_kwargs = {"format": "flac"}

        elif ext == "wav":
            export_kwargs = {"format": "wav"}

        elif ext == "aac":
            bitrate = quality if quality.endswith("k") else "192k"
            export_kwargs = {"format": "adts", "bitrate": bitrate,
                             "codec": "aac"}
            out_path = out_path.replace(".aac", ".aac")

        elif ext == "m4a":
            bitrate = quality if quality.endswith("k") else "192k"
            export_kwargs = {"format": "mp4", "bitrate": bitrate,
                             "codec": "aac"}

        elif ext == "ogg":
            # ogg quality: q=3/5/7/9
            q_map = {"高 (q=9)": "9", "中高 (q=7)": "7",
                     "中 (q=5)": "5", "低 (q=3)": "3"}
            q = q_map.get(quality, "7")
            export_kwargs = {"format": "ogg", "codec": "libvorbis",
                             "parameters": ["-q:a", q]}

        elif ext == "opus":
            bitrate = quality if quality.endswith("k") else "128k"
            export_kwargs = {"format": "opus", "bitrate": bitrate}

        seg.export(out_path, **export_kwargs)
        return out_path

    except ImportError:
        raise RuntimeError(
            "❌ 缺少依赖：请运行 pip install soundfile pydub\n"
            "   有损格式还需要系统安装 ffmpeg"
        )


# ── ComfyUI 节点 ──────────────────────────────────────────────────────────────

class FlywayAudioSave:
    """🐦‍🔥 音频保存"""

    @classmethod
    def INPUT_TYPES(cls):
        # 默认保存路径：ComfyUI/output/audio/
        default_dir = os.path.join(folder_paths.get_output_directory(), "audio")
        return {
            "required": {
                "audio": ("AUDIO",),
                "format": (FORMAT_KEYS, {"default": DEFAULT_FORMAT}),
                "quality": (ALL_QUALITY_OPTIONS, {"default": "无损 (原样)"}),
                "save_directory": ("STRING", {
                    "default": default_dir,
                    "multiline": False,
                }),
            },
            "optional": {
                "filename": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "留空则自动生成时间戳文件名",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("filepath", "filename")
    FUNCTION = "save"
    CATEGORY = "flyway"
    OUTPUT_NODE = True

    def save(self, audio, format: str, quality: str,
             save_directory: str, filename: str = ""):

        # ── 解析 audio 输入 ──────────────────────────────────────────────────
        sample_rate = 44100
        if isinstance(audio, dict):
            sample_rate = audio.get("sample_rate", 44100)
            waveform_raw = audio
        else:
            waveform_raw = audio

        waveform_np, sample_rate = _tensor_to_numpy(waveform_raw, sample_rate)

        # ── 准备保存目录 ─────────────────────────────────────────────────────
        save_dir = os.path.abspath(save_directory)
        os.makedirs(save_dir, exist_ok=True)

        # ── 文件名 ───────────────────────────────────────────────────────────
        cfg = FORMAT_CONFIG[format]
        ext = cfg["ext"]

        if filename and filename.strip():
            stem = _safe_filename(filename)
            # 移除用户可能带的扩展名
            stem = os.path.splitext(stem)[0]
        else:
            stem = datetime.datetime.now().strftime("audio_%Y%m%d_%H%M%S")

        out_path = _unique_path(save_dir, stem, ext)

        # ── 质量有效性检查：无损格式忽略质量设置 ────────────────────────────
        effective_quality = quality
        if cfg["lossless"]:
            effective_quality = "无损 (原样)"

        # ── 保存 ─────────────────────────────────────────────────────────────
        saved_path = _save_audio(waveform_np, sample_rate,
                                 out_path, format, effective_quality)

        fname = os.path.basename(saved_path)
        size_kb = os.path.getsize(saved_path) / 1024

        print(
            f"🐦‍🔥 Flyway AudioSave: 已保存\n"
            f"   格式   : {format}  质量: {effective_quality}\n"
            f"   路径   : {saved_path}\n"
            f"   大小   : {size_kb:.1f} KB\n"
            f"   采样率 : {sample_rate} Hz  "
            f"声道: {waveform_np.shape[1] if waveform_np.ndim == 2 else 1}"
        )

        return (saved_path, fname)


# ── 注册 ──────────────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlywayAudioSave": FlywayAudioSave,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywayAudioSave": "🐦‍🔥 音频保存",
}
