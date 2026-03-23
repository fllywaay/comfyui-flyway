"""
ComfyUI Flyway Plugin
一个专用的 ComfyUI 插件，包含图片批处理、文本输入和音频工具等功能
🐦‍🔥 Image List ↔ Directory - 保存和读取批量图片
🐦‍🔥 逻辑过滤 - 布尔条件输出
🐦‍🔥 多行文本轮询 - 处理多行文本，输出顺序/随机段落
🐦‍🔥 Fish S2 Token 估算 - 预估 Fish Audio S2 TTS token 数与音频时长
🐦‍🔥 音频保存 - 将音频保存为常见格式（wav/flac/mp3/aac/ogg/m4a/opus）
🐦‍🔥 音频时间对齐 - 将目标音频 DTW 对齐到参考音频时间轴（如中文配音对齐英文原声）
"""

from .flyway_nodes import (
    NODE_CLASS_MAPPINGS as _MAPPINGS_MAIN,
    NODE_DISPLAY_NAME_MAPPINGS as _NAMES_MAIN,
)
from .flyway_audio_save import (
    NODE_CLASS_MAPPINGS as _MAPPINGS_AUDIO,
    NODE_DISPLAY_NAME_MAPPINGS as _NAMES_AUDIO,
)
from .flyway_audio_align import (
    NODE_CLASS_MAPPINGS as _MAPPINGS_ALIGN,
    NODE_DISPLAY_NAME_MAPPINGS as _NAMES_ALIGN,
)

NODE_CLASS_MAPPINGS        = {**_MAPPINGS_MAIN, **_MAPPINGS_AUDIO, **_MAPPINGS_ALIGN}
NODE_DISPLAY_NAME_MAPPINGS = {**_NAMES_MAIN,    **_NAMES_AUDIO,    **_NAMES_ALIGN}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

PLUGIN_NAME    = "comfyui-flyway"
PLUGIN_VERSION = "1.3.0"
PLUGIN_AUTHOR  = "switflynet"