"""
ComfyUI Flyway Plugin - Subtitle & Translate  v2.0
🐦‍🔥 Subtitle & Translate

segment_mode:
  punctuation  – pure punctuation/pause split, no LLM
  llm          – LLM sentence grouping (OpenAI-compatible API)

Translation is triggered only when target_language is non-empty.
translate_system_prompt is fully editable in the node.
"""

import re
import json
import urllib.request

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

# ── timestamp parser ──────────────────────────────────────────────────────────

def parse_timestamps(ts_text: str) -> list[dict]:
    entries = []
    for line in ts_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'(\d+\.?\d*)\s*-\s*(\d+\.?\d*)\s*:\s*(.*)', line)
        if m:
            entries.append({
                "start": float(m.group(1)),
                "end":   float(m.group(2)),
                "word":  m.group(3).strip(),
            })
    return entries

# ── time formatters ───────────────────────────────────────────────────────────

def _srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    h,  ms  = divmod(ms, 3_600_000)
    m,  ms  = divmod(ms,    60_000)
    sec, ms = divmod(ms,     1_000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"

def _vtt_time(s: float) -> str:
    return _srt_time(s).replace(",", ".")

def to_srt(segs: list[dict]) -> str:
    out = []
    for i, s in enumerate(segs, 1):
        out += [str(i), f"{_srt_time(s['start'])} --> {_srt_time(s['end'])}", s["text"], ""]
    return "\n".join(out)

def to_vtt(segs: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for i, s in enumerate(segs, 1):
        out += [f"cue-{i:04d}", f"{_vtt_time(s['start'])} --> {_vtt_time(s['end'])}", s["text"], ""]
    return "\n".join(out)

def to_plain(segs: list[dict]) -> str:
    return "\n".join(s["text"] for s in segs)

# ── OpenAI-compatible API (works with Ollama /v1, vLLM, etc.) ────────────────

def get_models(base_url: str) -> list[str]:
    # Try OpenAI-compatible /v1/models first
    try:
        url = base_url.rstrip("/") + "/v1/models"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            data   = json.loads(r.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            if models:
                return sorted(models)
    except Exception:
        pass
    # Fallback: Ollama native /api/tags
    try:
        url = base_url.rstrip("/") + "/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            return sorted(m["name"] for m in data.get("models", []))
    except Exception:
        return []

def unload_model(base_url: str, model: str):
    """Ollama-specific: release model from VRAM."""
    try:
        payload = json.dumps({"model": model, "keep_alive": 0}).encode()
        req = urllib.request.Request(
            base_url.rstrip("/") + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass

def chat(base_url: str, model: str, system: str, user: str,
         temperature: float, top_p: float, top_k: int,
         repeat_penalty: float, num_ctx: int, timeout: int,
         stop_tokens: list | None = None) -> str:
    """
    OpenAI-compatible /v1/chat/completions.
    Extra keys (top_k, repeat_penalty) are silently ignored by strict servers.
    """
    payload: dict = {
        "model":       model,
        "messages":    [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream":      False,
        "temperature": temperature,
        "top_p":       top_p,
        "max_tokens":  num_ctx,
        # Ollama / local extensions
        "top_k":          top_k,
        "repeat_penalty": repeat_penalty,
    }
    if stop_tokens:
        payload["stop"] = stop_tokens

    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))

    content = resp["choices"][0]["message"]["content"].strip()
    # Strip leaked special tokens
    content = re.sub(r'<\|[^|]+\|>', '', content).strip()
    return content

# ── punctuation / pause segmentation (no LLM) ────────────────────────────────

_SENT_END = re.compile(r'[。！？!?\.…]+$')
_CLAUSE   = re.compile(r'[,，；;、]+$')

def _is_cjk(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u30ff]', text))

def _punct_segment(words: list[dict],
                   min_words: int = 3,
                   max_words: int = 18,
                   pause_threshold: float = 0.35) -> list[dict]:
    """
    Split into subtitle lines using punctuation + silence pauses only.
    Flush rules (in priority order):
      1. Previous word ends with sentence-ending punctuation
      2. Gap to next word >= pause_threshold seconds
      3. Previous word ends with clause punctuation AND current group >= min_words
      4. Current group has reached max_words (hard cap)
    """
    if not words:
        return []

    groups: list[list[dict]] = []
    cur: list[dict] = [words[0]]

    for w in words[1:]:
        gap       = w["start"] - cur[-1]["end"]
        prev_word = cur[-1]["word"]

        if (
            _SENT_END.search(prev_word)
            or gap >= pause_threshold
            or (_CLAUSE.search(prev_word) and len(cur) >= min_words)
            or len(cur) >= max_words
        ):
            groups.append(cur)
            cur = [w]
        else:
            cur.append(w)

    if cur:
        groups.append(cur)

    segs = []
    for g in groups:
        is_cjk = any(_is_cjk(w["word"]) for w in g)
        sep    = "" if is_cjk else " "
        text   = sep.join(w["word"] for w in g).strip()
        segs.append({"start": g[0]["start"], "end": g[-1]["end"], "text": text})
    return segs

# ── LLM segmentation ──────────────────────────────────────────────────────────

SEGMENT_SYSTEM = """\
You are a professional subtitle segmentation assistant.

Task: group word-level ASR timestamps into natural subtitle lines.

Rules:
- Target 6-14 words per subtitle (12-30 chars for CJK)
- Split at sentence or clause boundaries; respect punctuation and natural pauses
- Never break mid-phrase, mid-name, or mid-number
- Output ONLY a JSON array of index groups — no markdown, no explanation

Input format:
[index] start-end: word

Output format (pure JSON only):
[[0,1,2,3],[4,5,6,7],[8,9,10]]
"""

def _build_llm_input(words: list[dict]) -> str:
    return "\n".join(
        f"[{i}] {w['start']:.2f}-{w['end']:.2f}: {w['word']}"
        for i, w in enumerate(words)
    )

def _parse_llm_response(resp: str, words: list[dict]) -> list[dict]:
    resp = resp.strip()
    m = re.search(r'\[\s*\[.*?\]\s*\]', resp, re.DOTALL)
    if m:
        resp = m.group(0)
    try:
        groups = json.loads(resp)
    except Exception:
        print("[Flyway] LLM response parse failed — falling back to punctuation segmentation")
        return _punct_segment(words)

    segs = []
    for group in groups:
        if not group:
            continue
        indices = sorted(set(i for i in group if 0 <= i < len(words)))
        if not indices:
            continue
        chunk  = [words[i] for i in indices]
        is_cjk = any(_is_cjk(w["word"]) for w in chunk)
        sep    = "" if is_cjk else " "
        text   = sep.join(w["word"] for w in chunk).strip()
        segs.append({"start": chunk[0]["start"], "end": chunk[-1]["end"], "text": text})

    return segs if segs else _punct_segment(words)

# ── translation ───────────────────────────────────────────────────────────────

DEFAULT_TRANSLATE_PROMPT = """\
You are a professional subtitle translator.

Rules:
- Copy ALL index numbers and timestamp lines EXACTLY as-is (do NOT modify them)
- Timestamp format example: 00:01:23,456 --> 00:01:25,789  — copy verbatim
- Translate ONLY the subtitle text lines
- Keep the EXACT same number of subtitle blocks — do NOT merge or split any blocks
- Do NOT add explanations, notes, or extra content
- Output ONLY the translated subtitle, nothing else

Target language: {target_language}"""

def translate_subtitle(subtitle: str, base_url: str, model: str,
                        target_language: str, system_prompt_tpl: str,
                        temperature: float, top_p: float, top_k: int,
                        repeat_penalty: float, num_ctx: int, timeout: int) -> str:
    system = system_prompt_tpl.replace("{target_language}", target_language)
    return chat(
        base_url, model, system, subtitle,
        temperature, top_p, top_k, repeat_penalty,
        num_ctx, timeout,
        stop_tokens=["<|endoftext|>", "<|im_end|>", "<|im_start|>", "</s>"],
    )

def subtitle_to_plain(subtitle: str) -> str:
    ts = re.compile(r'^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}')
    lines = []
    for line in subtitle.splitlines():
        line = line.strip()
        if not line:
            continue
        if ts.match(line) or re.match(r'^\d+$', line):
            continue
        if line == "WEBVTT" or re.match(r'^cue-\d+$', line):
            continue
        lines.append(line)
    return "\n".join(lines)

# ── node ──────────────────────────────────────────────────────────────────────

class FlywaySubtitleTranslate:

    FORMAT_OPTIONS  = ["SRT", "WebVTT"]
    SEGMENT_OPTIONS = ["punctuation", "llm"]
    _model_cache: dict = {}

    @classmethod
    def _get_models(cls, url: str) -> list[str]:
        if url not in cls._model_cache:
            models = get_models(url)
            cls._model_cache[url] = models if models else ["(no models found)"]
        return cls._model_cache[url]

    @classmethod
    def INPUT_TYPES(cls):
        models = cls._get_models(DEFAULT_OLLAMA_URL)
        return {
            "required": {
                # ── Input ────────────────────────────────────────────────────
                "timestamps": ("STRING", {
                    "multiline": True,
                    "default": (
                        "0.08-0.24: It's\n"
                        "0.24-0.56: not\n"
                        "0.56-1.20: about\n"
                        "1.20-1.60: what\n"
                        "1.60-2.00: we\n"
                        "2.00-2.50: have."
                    ),
                }),

                # ── Segmentation ─────────────────────────────────────────────
                "segment_mode": (cls.SEGMENT_OPTIONS, {"default": "punctuation"}),
                "subtitle_format": (cls.FORMAT_OPTIONS, {"default": "SRT"}),

                # ── API connection (used for llm mode and translation) ────────
                "api_base_url": ("STRING", {
                    "default":   DEFAULT_OLLAMA_URL,
                    "multiline": False,
                }),
                "model_list": (models, {"default": models[0]}),
                "custom_model": ("STRING", {
                    "default":   "",
                    "multiline": False,
                }),

                # ── LLM sampling ──────────────────────────────────────────────
                "temperature": ("FLOAT", {
                    "default": 0.2, "min": 0.0, "max": 2.0,
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
                    "default": 1.05, "min": 0.5, "max": 2.0,
                    "step": 0.05, "display": "number",
                }),
                "num_ctx": ("INT", {
                    "default": 8192, "min": 512, "max": 131072,
                    "step": 512, "display": "number",
                }),
                "timeout_seconds": ("INT", {
                    "default": 300, "min": 30, "max": 3600,
                    "step": 30, "display": "number",
                }),

                # ── Translation ───────────────────────────────────────────────
                # Leave target_language blank to skip translation
                "target_language": ("STRING", {
                    "default":   "Chinese",
                    "multiline": False,
                }),
                "translate_system_prompt": ("STRING", {
                    "multiline": True,
                    "default":   DEFAULT_TRANSLATE_PROMPT,
                }),

                "unload_after": ("BOOLEAN", {
                    "default":   False,
                    "label_on":  "Unload model after",
                    "label_off": "Keep in VRAM",
                }),
            },
            "optional": {
                # Raw source text passed as context to LLM segmenter
                "source_text": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING")
    RETURN_NAMES  = (
        "subtitle",             # source SRT / WebVTT with timestamps
        "translated_subtitle",  # translated SRT / WebVTT  (empty string if skipped)
        "plain_lines",          # plain text — translated if available, else source
    )
    FUNCTION    = "process"
    CATEGORY    = "flyway"
    OUTPUT_NODE = False

    def process(self, timestamps, segment_mode, subtitle_format,
                api_base_url, model_list, custom_model,
                temperature, top_p, top_k, repeat_penalty,
                num_ctx, timeout_seconds,
                target_language, translate_system_prompt, unload_after,
                source_text=""):

        words = parse_timestamps(timestamps)
        if not words:
            print("[Flyway] SubtitleTranslate: no valid timestamp lines found")
            return ("", "", "")

        model = custom_model.strip() if custom_model.strip() else model_list

        # ── Step 1: segmentation ──────────────────────────────────────────────
        print(f"[Flyway] SubtitleTranslate: {len(words)} words | mode={segment_mode} | model={model}")

        if segment_mode == "punctuation":
            segs = _punct_segment(words)
        else:
            llm_input = _build_llm_input(words)
            if source_text.strip():
                llm_input = (
                    f"Source text for reference:\n{source_text.strip()}\n\n"
                    f"Word timestamps:\n{llm_input}"
                )
            try:
                resp = chat(
                    api_base_url, model, SEGMENT_SYSTEM, llm_input,
                    temperature=0.1, top_p=0.95, top_k=20,
                    repeat_penalty=1.0, num_ctx=max(4096, num_ctx),
                    timeout=timeout_seconds,
                    stop_tokens=["<|endoftext|>", "<|im_end|>", "<|im_start|>", "</s>"],
                )
                segs = _parse_llm_response(resp, words)
            except Exception as e:
                print(f"[Flyway] LLM segmentation failed — punctuation fallback: {e}")
                segs = _punct_segment(words)

        subtitle = to_srt(segs) if subtitle_format == "SRT" else to_vtt(segs)
        print(f"[Flyway] SubtitleTranslate: {len(segs)} segments → {subtitle_format}")

        # ── Step 2: translation (skip if target_language is blank) ────────────
        if not target_language.strip():
            plain = to_plain(segs)
            if unload_after:
                unload_model(api_base_url, model)
            return (subtitle, "", plain)

        print(f"[Flyway] SubtitleTranslate: translating → {target_language}")
        try:
            translated = translate_subtitle(
                subtitle, api_base_url, model,
                target_language, translate_system_prompt,
                temperature, top_p, top_k, repeat_penalty,
                num_ctx, timeout_seconds,
            )
        except Exception as e:
            raise RuntimeError(f"[Flyway] Translation failed: {e}")

        if unload_after:
            unload_model(api_base_url, model)

        plain = subtitle_to_plain(translated)
        print(f"[Flyway] SubtitleTranslate: done — {len(segs)} segs, {len(translated)} chars")
        return (subtitle, translated, plain)


# ── register ──────────────────────────────────────────────────────────────────

NODE_CLASS_MAPPINGS = {
    "FlywaySubtitleTranslate": FlywaySubtitleTranslate,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywaySubtitleTranslate": "🐦‍🔥 Subtitle & Translate",
}