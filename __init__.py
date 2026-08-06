"""
ComfyUI Flyway Plugin v1.5.0
🐦‍🔥 Image List ↔ Directory
🐦‍🔥 Logic Filter
🐦‍🔥 Multiline Text Input
🐦‍🔥 Fish S2 Token Estimator
🐦‍🔥 Audio Save
🐦‍🔥 Subtitle & Translate
🐦‍🔥 Ollama Translate  (standalone)
🐦‍🔥 TTS Merge
"""

from .flyway_nodes              import NODE_CLASS_MAPPINGS as _M1, NODE_DISPLAY_NAME_MAPPINGS as _N1
from .flyway_audio_save         import NODE_CLASS_MAPPINGS as _M2, NODE_DISPLAY_NAME_MAPPINGS as _N2
from .flyway_subtitle_translate import NODE_CLASS_MAPPINGS as _M3, NODE_DISPLAY_NAME_MAPPINGS as _N3
from .flyway_ollama_translate   import NODE_CLASS_MAPPINGS as _M4, NODE_DISPLAY_NAME_MAPPINGS as _N4
from .flyway_tts_merge          import NODE_CLASS_MAPPINGS as _M5, NODE_DISPLAY_NAME_MAPPINGS as _N5

NODE_CLASS_MAPPINGS        = {**_M1, **_M2, **_M3, **_M4, **_M5}
NODE_DISPLAY_NAME_MAPPINGS = {**_N1, **_N2, **_N3, **_N4, **_N5}

# 🌟 新增：告诉 ComfyUI 你的前端扩展代码存放在 js 文件夹中
WEB_DIRECTORY = "./js"

# 🌟 修改：将 'WEB_DIRECTORY' 暴露给 ComfyUI 引擎
__all__ =['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

PLUGIN_NAME    = "comfyui-flyway"
PLUGIN_VERSION = "1.5.0"
PLUGIN_AUTHOR  = "switflynet"