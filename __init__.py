"""
ComfyUI Flyway Plugin v1.6.0
🐦‍🔥 Image List ↔ Directory
🐦‍🔥 Logic Filter
🐦‍🔥 Multiline Text Input
🐦‍🔥 Fish S2 Token Estimator
🐦‍🔥 Audio Save
🐦‍🔥 Subtitle & Translate
🐦‍🔥 Ollama Translate  (standalone)
🐦‍🔥 TTS Merge
🐦‍🔥 Batch Image Save To Path      (merged from test-comfyui)
🐦‍🔥 Select Every Nth Image        (merged from test-comfyui)
🐦‍🔥 Florence2 Label Dedup         (merged from test-comfyui)
🐦‍🔥 Lyric Align -> LRC/SRT/ASS    (merged from test-comfyui)

Per-node notes: see NODES.md
"""

from .flyway_nodes              import NODE_CLASS_MAPPINGS as _M1, NODE_DISPLAY_NAME_MAPPINGS as _N1
from .flyway_audio_save         import NODE_CLASS_MAPPINGS as _M2, NODE_DISPLAY_NAME_MAPPINGS as _N2
from .flyway_subtitle_translate import NODE_CLASS_MAPPINGS as _M3, NODE_DISPLAY_NAME_MAPPINGS as _N3
from .flyway_ollama_translate   import NODE_CLASS_MAPPINGS as _M4, NODE_DISPLAY_NAME_MAPPINGS as _N4
from .flyway_tts_merge          import NODE_CLASS_MAPPINGS as _M5, NODE_DISPLAY_NAME_MAPPINGS as _N5
from .flyway_batch_image_save   import NODE_CLASS_MAPPINGS as _M6, NODE_DISPLAY_NAME_MAPPINGS as _N6
from .flyway_florence2_tools    import NODE_CLASS_MAPPINGS as _M7, NODE_DISPLAY_NAME_MAPPINGS as _N7
from .flyway_lyric_align        import NODE_CLASS_MAPPINGS as _M8, NODE_DISPLAY_NAME_MAPPINGS as _N8

NODE_CLASS_MAPPINGS        = {**_M1, **_M2, **_M3, **_M4, **_M5, **_M6, **_M7, **_M8}
NODE_DISPLAY_NAME_MAPPINGS = {**_N1, **_N2, **_N3, **_N4, **_N5, **_N6, **_N7, **_N8}

# Tell ComfyUI where the frontend extension code lives (js/ folder)
WEB_DIRECTORY = "./js"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

PLUGIN_NAME    = "comfyui-flyway"
PLUGIN_VERSION = "1.6.0"
PLUGIN_AUTHOR  = "switflynet"
