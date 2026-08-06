"""
ComfyUI Flyway Plugin - Ollama Translate Node
🐦‍🔥 Ollama Translate
Translate subtitle text using local or remote Ollama models.
"""

import re
import json
import urllib.request
import urllib.error

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional subtitle translator. "
    "Translate the provided subtitle text accurately and naturally. "
    "Rules:\n"
    "- Preserve ALL timestamp lines exactly as-is (lines like "
    "'00:00:01,000 --> 00:00:03,000' or 'WEBVTT' or sequence numbers).\n"
    "- Only translate the actual subtitle text lines.\n"
    "- Keep the same number of lines and subtitle blocks.\n"
    "- Do NOT add explanations or notes.\n"
    "- Output ONLY the translated subtitle, nothing else."
)


# ── Ollama API helpers ────────────────────────────────────────────────────────

def _ollama_request(url: str, payload: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_ollama_models(base_url: str) -> list[str]:
    """Fetch available model list from Ollama /api/tags."""
    try:
        url = base_url.rstrip("/") + "/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def unload_model(base_url: str, model: str) -> bool:
    """Send keep_alive=0 to unload model from VRAM."""
    try:
        payload = {"model": model, "keep_alive": 0}
        _ollama_request(base_url.rstrip("/") + "/api/generate", payload, timeout=10)
        return True
    except Exception:
        return False


def chat_with_ollama(base_url: str, model: str, system_prompt: str,
                     user_text: str, image_b64: str = "",
                     temperature: float = 0.3,
                     top_p: float = 0.9,
                     top_k: int = 40,
                     repeat_penalty: float = 1.1,
                     num_ctx: int = 4096,
                     timeout: int = 300) -> str:
    """Send chat request, return assistant content string."""
    messages = [{"role": "system", "content": system_prompt}]

    user_msg: dict = {"role": "user", "content": user_text}
    if image_b64:
        user_msg["images"] = [image_b64]
    messages.append(user_msg)

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature":    temperature,
            "top_p":          top_p,
            "top_k":          top_k,
            "repeat_penalty": repeat_penalty,
            "num_ctx":        num_ctx,
        },
    }
    resp = _ollama_request(
        base_url.rstrip("/") + "/api/chat", payload, timeout=timeout
    )
    return resp.get("message", {}).get("content", "").strip()


# ── subtitle plain-line extraction ───────────────────────────────────────────

def subtitle_to_plain(subtitle: str) -> str:
    """
    Extract only text lines from SRT/WebVTT, one sentence per line.
    Strips index numbers, timestamp lines, WEBVTT header.
    """
    lines = []
    ts_pattern = re.compile(
        r'^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}'
    )
    for line in subtitle.splitlines():
        line = line.strip()
        if not line:
            continue
        if line == "WEBVTT":
            continue
        if ts_pattern.match(line):
            continue
        if re.match(r'^\d+$', line):
            continue
        if re.match(r'^cue-\d+$', line):
            continue
        lines.append(line)
    return "\n".join(lines)


# ── node ──────────────────────────────────────────────────────────────────────

class FlywayOllamaTranslate:

    # Class-level model cache (refreshed on each node load)
    _cached_models: list[str] = []
    _cached_url: str = ""

    @classmethod
    def _refresh_models(cls, base_url: str) -> list[str]:
        if base_url != cls._cached_url:
            cls._cached_models = get_ollama_models(base_url)
            cls._cached_url = base_url
        return cls._cached_models or ["(no models found)"]

    @classmethod
    def INPUT_TYPES(cls):
        # Try to fetch models at node load time
        models = cls._refresh_models(DEFAULT_OLLAMA_URL)
        return {
            "required": {
                "subtitle_text": ("STRING", {
                    "multiline": True,
                    "default":   "",
                }),
                "ollama_url": ("STRING", {
                    "default":   DEFAULT_OLLAMA_URL,
                    "multiline": False,
                }),
                "model_list": (models, {"default": models[0]}),
                "custom_model": ("STRING", {
                    "default":   "",
                    "multiline": False,
                }),
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default":   DEFAULT_SYSTEM_PROMPT,
                }),
                "target_language": ("STRING", {
                    "default":   "Chinese",
                    "multiline": False,
                }),
                "temperature": ("FLOAT", {
                    "default": 0.3, "min": 0.0, "max": 2.0,
                    "step": 0.05, "display": "number",
                }),
                "top_p": ("FLOAT", {
                    "default": 0.9, "min": 0.0, "max": 1.0,
                    "step": 0.05, "display": "number",
                }),
                "top_k": ("INT", {
                    "default": 40, "min": 1, "max": 200,
                    "step": 1, "display": "number",
                }),
                "repeat_penalty": ("FLOAT", {
                    "default": 1.1, "min": 0.5, "max": 2.0,
                    "step": 0.05, "display": "number",
                }),
                "num_ctx": ("INT", {
                    "default": 4096, "min": 512, "max": 131072,
                    "step": 512, "display": "number",
                }),
                "timeout_seconds": ("INT", {
                    "default": 300, "min": 30, "max": 3600,
                    "step": 30, "display": "number",
                }),
                "unload_after": ("BOOLEAN", {
                    "default":   False,
                    "label_on":  "Unload model after",
                    "label_off": "Keep in VRAM",
                }),
            },
            "optional": {
                "image": ("IMAGE",),
            }
        }

    RETURN_TYPES  = ("STRING", "STRING")
    RETURN_NAMES  = ("translated_subtitle",  # full SRT/WebVTT with timestamps
                     "plain_lines")          # text only, one line per sentence
    FUNCTION      = "translate"
    CATEGORY      = "flyway"
    OUTPUT_NODE   = False

    def translate(self, subtitle_text, ollama_url, model_list,
                  custom_model, system_prompt, target_language,
                  temperature, top_p, top_k, repeat_penalty,
                  num_ctx, timeout_seconds, unload_after,
                  image=None):

        if not subtitle_text.strip():
            return ("", "")

        # Model selection: custom > list
        model = custom_model.strip() if custom_model.strip() else model_list

        # Encode image if provided
        image_b64 = ""
        if image is not None:
            try:
                import base64, io
                import numpy as np
                from PIL import Image as PILImage
                arr = (image[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                img = PILImage.fromarray(arr, "RGB")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            except Exception as e:
                print(f"[Flyway] OllamaTranslate: image encode failed: {e}")

        # Inject target language into system prompt
        full_system = (
            f"{system_prompt}\n\nTarget language: {target_language}"
        )

        print(f"[Flyway] OllamaTranslate: model={model} url={ollama_url}")

        try:
            result = chat_with_ollama(
                base_url=ollama_url,
                model=model,
                system_prompt=full_system,
                user_text=subtitle_text,
                image_b64=image_b64,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                repeat_penalty=repeat_penalty,
                num_ctx=num_ctx,
                timeout=timeout_seconds,
            )
        except Exception as e:
            raise RuntimeError(f"[Flyway] Ollama request failed: {e}")

        if unload_after:
            ok = unload_model(ollama_url, model)
            print(f"[Flyway] OllamaTranslate: unload model {model} -> {'ok' if ok else 'failed'}")

        plain = subtitle_to_plain(result)
        print(f"[Flyway] OllamaTranslate: done, {len(result)} chars")
        return (result, plain)


# ── register ──────────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlywayOllamaTranslate": FlywayOllamaTranslate,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywayOllamaTranslate": "🐦‍🔥 Ollama Translate",
}
