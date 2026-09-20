"""
Plain ASR transcription -> timestamped lyrics, no known-lyrics text needed.

Used by LyricAlignLRC when lyrics_text is empty: instead of aligning known
lyrics onto ASR timings (lyric-align's job), this just transcribes the audio
and writes out whatever Whisper heard, with segment timestamps, in lrc/srt/
vtt/json. ass/ttml/karaoke aren't implemented here (those need lyric-align's
own writers) - the node falls back to lrc for those and says so.

This is a helper script, NOT a node (it is not imported by __init__.py); the
node runs it in a subprocess.

Run as: python flyway_transcribe_only.py <audio> <model> <device> <language>
                                   <no_vad 0|1> <format> <output_path>
"""
import sys
import json


def fmt_ts_lrc(t):
    m = int(t // 60)
    s = t - m * 60
    return f"[{m:02d}:{s:05.2f}]"


def fmt_ts_srt(t):
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_ts_vtt(t):
    m = int(t // 60)
    s = t - m * 60
    return f"{m:02d}:{s:06.3f}"


def main():
    audio_path, model, device, language, no_vad_flag, out_format, output_path = sys.argv[1:8]
    no_vad = no_vad_flag == "1"

    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    whisper = WhisperModel(model, device=device, compute_type=compute_type)

    segments_gen, info = whisper.transcribe(
        audio_path,
        language=language or None,
        vad_filter=not no_vad,
        word_timestamps=True,
    )

    segments = []
    for seg in segments_gen:
        text = seg.text.strip()
        if not text:
            continue
        segments.append({"start": seg.start, "end": seg.end, "text": text})

    if out_format not in ("lrc", "srt", "vtt", "json"):
        # ass/ttml/karaoke/elrc need lyric-align's own writers, which need
        # matched lyric lines. Fall back to lrc and say so in the output.
        print(f"[transcribe_only] format '{out_format}' needs known lyrics; writing lrc instead", file=sys.stderr)
        out_format = "lrc"

    if out_format == "lrc":
        lines = [f"{fmt_ts_lrc(s['start'])}{s['text']}" for s in segments]
        content = "\n".join(lines) + "\n"
    elif out_format == "srt":
        parts = []
        for i, s in enumerate(segments, 1):
            parts.append(f"{i}\n{fmt_ts_srt(s['start'])} --> {fmt_ts_srt(s['end'])}\n{s['text']}\n")
        content = "\n".join(parts)
    elif out_format == "vtt":
        parts = ["WEBVTT\n"]
        for s in segments:
            parts.append(f"{fmt_ts_vtt(s['start'])} --> {fmt_ts_vtt(s['end'])}\n{s['text']}\n")
        content = "\n".join(parts)
    else:  # json
        content = json.dumps(segments, ensure_ascii=False, indent=2)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[transcribe_only] wrote {len(segments)} segments -> {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
