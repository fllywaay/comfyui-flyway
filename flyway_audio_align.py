"""
comfyui-flyway — 音频时间对齐 | Audio Time Align
使用 DTW（动态时间规整）将目标音频的时间轴对齐到参考音频。
典型用途：将中文配音对齐到英文原声，使每句话落在相同的时间轴上。

Uses DTW (Dynamic Time Warping) to align target audio's timeline to reference audio.
Typical use: align a Chinese dub to an English original so every sentence
lands at the same timestamp.

依赖 / Requirements:
    pip install librosa scipy
"""

import numpy as np
import torch

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False

try:
    from scipy.interpolate import interp1d
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


def _check_deps():
    missing = []
    if not HAS_LIBROSA:
        missing.append("librosa")
    if not HAS_SCIPY:
        missing.append("scipy")
    if missing:
        raise ImportError(
            f"缺少依赖 / Missing dependencies: {', '.join(missing)}\n"
            f"请执行 / Run: pip install {' '.join(missing)}"
        )


def _to_mono_numpy(waveform: torch.Tensor, orig_sr: int, target_sr: int) -> np.ndarray:
    """waveform: (batch, channels, samples) → mono float32 numpy array"""
    y = waveform[0].mean(dim=0).cpu().numpy().astype(np.float32)
    if orig_sr != target_sr:
        y = librosa.resample(y, orig_sr=orig_sr, target_sr=target_sr)
    return y


def _extract_features(y: np.ndarray, sr: int, feature_type: str,
                       n_features: int, hop_length: int) -> np.ndarray:
    if feature_type == "mfcc":
        feat = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_features, hop_length=hop_length)
    elif feature_type == "chroma":
        feat = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop_length)
    else:  # melspectrogram
        feat = librosa.power_to_db(
            librosa.feature.melspectrogram(y=y, sr=sr, n_mels=n_features, hop_length=hop_length)
        )
    return librosa.util.normalize(feat, axis=0)


class FlyWayAudioTimeAlign:
    """
    🐦‍🔥 音频时间对齐 | Audio Time Align

    将「目标音频」的时间轴 DTW 对齐到「参考音频」，输出时长与参考音频完全相同。
    Warps the target audio's timeline to match the reference audio using DTW.
    Output duration equals the reference audio exactly.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "reference_audio": ("AUDIO", {
                    "tooltip": "参考音频（时间轴基准，如英文原声）| Reference audio (timeline basis, e.g. English original)"
                }),
                "target_audio": ("AUDIO", {
                    "tooltip": "目标音频（将被拉伸/压缩以匹配参考，如中文配音）| Target audio to warp (e.g. Chinese dub)"
                }),
                "feature_type": (
                    ["mfcc", "chroma", "melspectrogram"],
                    {
                        "default": "mfcc",
                        "tooltip": (
                            "对齐所用特征 | Feature for alignment\n"
                            "mfcc：音色，适合人声/配音 | Timbre, best for speech/dub\n"
                            "chroma：音高，适合音乐 | Pitch, best for music\n"
                            "melspectrogram：综合频谱 | Full spectrum"
                        )
                    }
                ),
                "n_features": ("INT", {
                    "default": 20, "min": 12, "max": 128, "step": 4,
                    "tooltip": "特征维度（MFCC 系数数）| Feature dimensions (MFCC coefficients)"
                }),
                "hop_length": ("INT", {
                    "default": 512, "min": 128, "max": 2048, "step": 128,
                    "tooltip": (
                        "帧步长（采样点数）| Frame hop in samples\n"
                        "越小 → 对齐越精细但越慢 | Smaller = finer alignment but slower"
                    )
                }),
                "interpolation": (
                    ["linear", "nearest", "quadratic"],
                    {
                        "default": "linear",
                        "tooltip": "音频重采样插值方式 | Audio interpolation method"
                    }
                ),
            }
        }

    RETURN_TYPES  = ("AUDIO",)
    RETURN_NAMES  = ("aligned_audio",)
    FUNCTION      = "align"
    CATEGORY      = "flyway/音频 | audio"

    def align(
        self,
        reference_audio: dict,
        target_audio: dict,
        feature_type: str,
        n_features: int,
        hop_length: int,
        interpolation: str,
    ):
        _check_deps()

        ref_waveform = reference_audio["waveform"]
        tgt_waveform = target_audio["waveform"]
        ref_sr = int(reference_audio["sample_rate"])
        tgt_sr = int(target_audio["sample_rate"])
        work_sr = ref_sr

        # mono numpy for DTW
        ref_mono = _to_mono_numpy(ref_waveform, ref_sr, work_sr)
        tgt_mono = _to_mono_numpy(tgt_waveform, tgt_sr, work_sr)

        # feature extraction
        ref_feat = _extract_features(ref_mono, work_sr, feature_type, n_features, hop_length)
        tgt_feat = _extract_features(tgt_mono, work_sr, feature_type, n_features, hop_length)

        # DTW  →  wp[:, 0] = ref frames, wp[:, 1] = tgt frames
        _, wp = librosa.sequence.dtw(X=ref_feat, Y=tgt_feat, metric="cosine")
        wp = wp[::-1]

        uniq_ref, uniq_idx = np.unique(wp[:, 0].astype(np.float64), return_index=True)
        uniq_tgt = wp[:, 1].astype(np.float64)[uniq_idx]

        frame_map = interp1d(
            uniq_ref, uniq_tgt,
            kind="linear",
            bounds_error=False,
            fill_value=(uniq_tgt[0], uniq_tgt[-1]),
        )

        # ref sample index → tgt sample position
        ref_n_samples       = ref_waveform.shape[-1]
        tgt_n_samples       = len(tgt_mono)
        ref_frame_max       = float(ref_feat.shape[1] - 1)

        ref_sample_idx  = np.arange(ref_n_samples, dtype=np.float64)
        ref_frame_pos   = np.clip(ref_sample_idx / hop_length, 0.0, ref_frame_max)
        tgt_frame_pos   = frame_map(ref_frame_pos)
        tgt_sample_pos  = np.clip(tgt_frame_pos * hop_length, 0.0, tgt_n_samples - 1.0)

        # warp all channels
        tgt_n_channels = tgt_waveform.shape[1]
        warped = []
        for c in range(tgt_n_channels):
            ch = tgt_waveform[0, c].cpu().numpy().astype(np.float32)
            if tgt_sr != work_sr:
                ch = librosa.resample(ch, orig_sr=tgt_sr, target_sr=work_sr)
            src_idx = np.arange(len(ch), dtype=np.float64)
            f = interp1d(src_idx, ch, kind=interpolation,
                         bounds_error=False, fill_value=(float(ch[0]), float(ch[-1])))
            warped.append(f(tgt_sample_pos).astype(np.float32))

        out_tensor = torch.from_numpy(np.stack(warped, axis=0)).unsqueeze(0)
        return ({"waveform": out_tensor, "sample_rate": work_sr},)


# ── registration ──────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlyWayAudioTimeAlign": FlyWayAudioTimeAlign,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlyWayAudioTimeAlign": "🐦‍🔥 音频时间对齐 | Audio Time Align",
}