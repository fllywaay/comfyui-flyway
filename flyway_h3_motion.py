"""
ComfyUI Flyway Plugin - MiniMax H3 continuity nodes
🐦‍🔥 H3 Motion Context (Directory)
🐦‍🔥 H3 Motion Context (Image)
🐦‍🔥 Image Batch Extend With Overlap

Building blocks for chaining MiniMax H3 clips so that each clip continues the
previous one - clip by clip, or inside a Loop:

  previous clip's tail --> [Motion Context] --> anchored at frame 0 of the next clip
  frames so far + new clip --> [Extend With Overlap] --> one video, no duplicated frames

How the context works (same mechanism as the native "Add Guide for MiniMax H3"):
the last N frames of the previous clip are VAE-encoded and anchored at frame 0
of the next clip as a guide clip. The model only requires N to land on its
17k+5 grid (5, 22, 39, 56, 73, 90...); `context_length` is a free integer and
gets snapped DOWN to the nearest valid value automatically (same snapping the
native node does internally), so there is nothing to keep in sync with the
MAX_REF_VIDEO_FRAMES-style limits elsewhere. The first N frames the sampler
returns are therefore that context again, which is why the join node drops
`context_frames` frames.

ComfyUI-side dependencies (comfy.utils, node_helpers, the H3 model module) are
imported lazily inside the functions, so a ComfyUI build without MiniMax H3
support can still load the rest of this plugin.
"""
import os
import re
import math

import numpy as np
import torch
from PIL import Image, ImageOps

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _norm_dir(directory):
    return (directory or "").strip().strip('"')


def _natural_key(name):
    # re.split with a capture group alternates str, digits, str, ... so keys
    # from different names always compare str-with-str and int-with-int.
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def _list_frames(directory, sort_by="name"):
    directory = _norm_dir(directory)
    if not directory or not os.path.isdir(directory):
        return []
    entries = []
    with os.scandir(directory) as it:
        for e in it:
            if e.is_file() and e.name.lower().endswith(_IMAGE_EXTS):
                entries.append(e)
    if sort_by == "modified_time":
        entries.sort(key=lambda e: (e.stat().st_mtime_ns, _natural_key(e.name)))
    else:
        entries.sort(key=lambda e: _natural_key(e.name))
    return [e.path for e in entries]


def _protected_dirs():
    """Folders that must never be bulk-cleared, even if the user points at them."""
    protected = {os.path.abspath(os.path.expanduser("~"))}
    try:
        import folder_paths
        for getter in ("get_output_directory", "get_input_directory"):
            fn = getattr(folder_paths, getter, None)
            if fn:
                protected.add(os.path.abspath(fn()))
    except Exception:
        pass
    return {os.path.normcase(p) for p in protected}


def _clear_images(directory):
    """Delete image files (only) directly inside `directory`; returns how many.

    Non-recursive, never touches non-image files or sub-folders, does nothing if
    the folder does not exist, and refuses drive roots, the home folder and
    ComfyUI's output/input roots (a mistyped path must not wipe those).
    """
    d = _norm_dir(directory)
    if not d or not os.path.isdir(d):
        return 0
    real = os.path.abspath(d)
    if os.path.dirname(real) == real or os.path.normcase(real) in _protected_dirs():
        raise ValueError(
            f"H3 Motion Context: refusing to clear '{real}' (drive root, home, or ComfyUI input/output root). "
            "Use a dedicated sub-folder."
        )
    removed = 0
    for name in os.listdir(real):
        full = os.path.join(real, name)
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in _IMAGE_EXTS:
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    return removed


def _pick_frame_count(available, wanted, target_frames):
    """Largest valid guide length: 17k+5 frames (5, 22, 39, 56...), else 1 frame.

    Never longer than the frames available, the requested context_length, or
    (target_frames - 1) so the new clip always has something left to generate.
    """
    limit = min(int(wanted), int(available), int(target_frames) - 1)
    if limit < 1:
        return 0
    if limit < 5:
        return 1
    n = limit
    while n % 17 != 5:
        n -= 1
    return n


def _load_frames(paths):
    frames, size = [], None
    for p in paths:
        with Image.open(p) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            if size is None:
                size = im.size
            elif im.size != size:
                im = im.resize(size, Image.BICUBIC)
            frames.append(torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0))
    return torch.stack(frames, 0)  # [N, H, W, 3], 0..1


def _as_rgb_frames(images):
    """Validate an IMAGE batch and return float32 [N, H, W, 3] on the CPU."""
    if not isinstance(images, torch.Tensor) or images.ndim != 4:
        raise ValueError("H3 Motion Context (Image): context_images must be an IMAGE batch [frames, H, W, C].")
    x = images.detach().to("cpu", torch.float32)
    if x.shape[-1] == 1:
        x = x.expand(-1, -1, -1, 3)
    elif x.shape[-1] > 3:
        x = x[..., :3]
    return x.contiguous()


def _latent_geometry(latent):
    """(width, height, frame_count) of the clip a MiniMax H3 AV latent describes."""
    try:
        from comfy.ldm.minimax.model import FRAME_PER_TOKEN
    except ImportError as e:  # pragma: no cover - depends on the ComfyUI build
        raise RuntimeError("H3 Motion Context needs a ComfyUI build with MiniMax H3 support.") from e
    samples = latent["samples"]
    if not samples.is_nested or len(samples.tensors) != 2 or samples.tensors[0].ndim != 5:
        raise ValueError("H3 Motion Context: latent must be a MiniMax H3 AV latent.")
    video = samples.tensors[0]
    height, width = int(video.shape[3]) * 16, int(video.shape[4]) * 16
    frame_count = sum(FRAME_PER_TOKEN[k % 5] for k in range(video.shape[2]))
    return width, height, frame_count


def _fit(frames, width, height):
    # Same as the native guide: lanczos + center cover-crop to the latent canvas.
    import comfy.utils
    x = frames.movedim(-1, 1)
    x = comfy.utils.common_upscale(x, width, height, "lanczos", "center")
    return x.movedim(1, -1)


def _anchor(positive, vae, frames):
    """Add `frames` as a guide clip at frame 0 (keeps any keyframes already present)."""
    import node_helpers
    keyframe = {"resolved_frame_index": 0, "latent": vae.encode(frames)}
    keyframes = list(positive[0][1].get("minimax_keyframes", [])) if positive else []
    keyframes.append(keyframe)
    return node_helpers.conditioning_set_values(positive, {"minimax_keyframes": keyframes})


def _save_image_frames(directory, frames):
    """Append `frames` [N,H,W,3] float 0..1 as new numbered PNGs; returns how many were written.

    Numbering continues from however many image files are already in `directory`
    (found the same way _list_frames does), so repeated calls build one
    continuous sequence without needing an external counter.
    """
    d = _norm_dir(directory)
    if not d:
        raise ValueError("cache_path is empty.")
    os.makedirs(d, exist_ok=True)
    start = len(_list_frames(d))
    arr = (frames.clamp(0, 1).cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
    for i in range(arr.shape[0]):
        Image.fromarray(arr[i]).save(os.path.join(d, f"frame_{start + i:08d}.png"))
    return arr.shape[0]


def _load_all_frames(directory):
    """Read every cached frame back as one [N,H,W,3] float batch, oldest first."""
    paths = _list_frames(directory)
    if not paths:
        return torch.zeros(0, 0, 0, 3)
    return _load_frames(paths)


def _read_tail_images(directory, k):
    """Read only the last k cached frames from disk (bounded I/O), or None if empty/k<=0.

    Used as the 'source' for overlap math in disk mode, so a Loop never has to
    read back the whole growing video just to dedupe the next clip.
    """
    if k <= 0:
        return None
    paths = _list_frames(directory)
    if not paths:
        return None
    return _load_frames(paths[-k:])


# ---------------------------------------------------------------------------
# 1) Motion Context (Directory)
# ---------------------------------------------------------------------------
class FlywayH3MotionContextDir:
    """
    Reads the last N frames of the previous clip from a folder of images and
    anchors them at frame 0 of the clip being generated.

    - Empty / missing / blank folder  ->  skipped, conditioning passes through
      unchanged and context_frames = 0. The first clip needs no special wiring.
    - clear_directory = True  ->  the image files in the folder are deleted
      FIRST, then the (now empty) folder is read, i.e. this run is skipped.
      Drive it from a logic node (e.g. index == 0) so the first iteration of a
      Loop never picks up frames left over from a previous task.
    - Only image files directly inside the folder are ever deleted; sub-folders
      and other files are left alone.

    In a Loop, carry the folder path through the loop (e.g. the output_path of
    Batch Image Save To Path -> Loop Close -> next iteration's `directory`). That
    wire is what guarantees iteration k+1 reads AFTER iteration k has saved.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "latent": ("LATENT", {"tooltip": "The MiniMax H3 AV latent of the clip being generated (gives resolution and length)."}),
                "vae": ("VAE",),
                "directory": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "Folder holding the PREVIOUS clip's frames (png/jpg/webp/bmp/tif). Empty or missing = skip (first clip).",
                }),
                "context_length": ("INT", {
                    "default": 22, "min": 1, "max": 3600, "step": 1,
                    "tooltip": "How many trailing frames to use as motion context. Any value works - it's snapped down to the model's nearest valid guide length (5, 22, 39, 56, 73...). Reduced further if the folder or the clip is shorter.",
                }),
                "sort_by": (["name", "modified_time"], {"default": "name"}),
                "clear_directory": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "True: delete the image files in `directory` before reading (so this run skips). Wire it to a first-iteration switch to discard leftovers from an earlier task.",
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "INT", "STRING")
    RETURN_NAMES = ("positive", "context_frames", "status")
    FUNCTION = "apply"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        # Reads (and may delete) files on disk, so the inputs never describe the
        # real state. Always re-run - same reasoning as Batch Image Save To Path;
        # a folder fingerprint is unreliable inside a Loop.
        return float("nan")

    def apply(self, positive, latent, vae, directory, context_length, sort_by, clear_directory):
        width, height, frame_count = _latent_geometry(latent)

        cleared = _clear_images(directory) if clear_directory else 0
        prefix = f"cleared {cleared} image(s); " if clear_directory else ""

        paths = _list_frames(directory, sort_by)
        if not paths:
            return (positive, 0, prefix + "skipped: no frames in directory (first clip)")
        n = _pick_frame_count(len(paths), context_length, frame_count)
        if n == 0:
            return (positive, 0, prefix + "skipped: clip too short for a context")

        tail = paths[-n:]
        frames = _fit(_load_frames(tail), width, height)
        out = _anchor(positive, vae, frames)
        status = f"{prefix}context: {n} frames, {os.path.basename(tail[0])} .. {os.path.basename(tail[-1])}"
        return (out, n, status)


# ---------------------------------------------------------------------------
# 2) Motion Context (Image)
# ---------------------------------------------------------------------------
class FlywayH3MotionContextImage:
    """
    Same as the Directory version, but the previous clip's frames arrive as an
    IMAGE batch (any length; only the last N frames are used). Meant for Loops
    where the frames are carried in memory from one iteration to the next.

    context_images not connected / None / empty  ->  skipped (context_frames = 0),
    which is exactly what a Loop's first iteration hands over when the starting
    value is left unconnected.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "positive": ("CONDITIONING",),
                "latent": ("LATENT", {"tooltip": "The MiniMax H3 AV latent of the clip being generated (gives resolution and length)."}),
                "vae": ("VAE",),
                "context_length": ("INT", {
                    "default": 22, "min": 1, "max": 3600, "step": 1,
                    "tooltip": "How many trailing frames to use as motion context. Any value works - it's snapped down to the model's nearest valid guide length (5, 22, 39, 56, 73...). Reduced further if fewer frames are supplied or the clip is shorter.",
                }),
            },
            "optional": {
                "context_images": ("IMAGE", {"tooltip": "Frames of the previous clip (or of everything so far). Only the last N are used. None/empty = skip."}),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "INT", "STRING")
    RETURN_NAMES = ("positive", "context_frames", "status")
    FUNCTION = "apply"
    CATEGORY = "flyway"

    def apply(self, positive, latent, vae, context_length, context_images=None):
        width, height, frame_count = _latent_geometry(latent)

        if context_images is None:
            return (positive, 0, "skipped: no context images (first clip)")
        frames = _as_rgb_frames(context_images)
        if frames.shape[0] == 0:
            return (positive, 0, "skipped: empty context images (first clip)")
        n = _pick_frame_count(frames.shape[0], context_length, frame_count)
        if n == 0:
            return (positive, 0, "skipped: clip too short for a context")

        frames = _fit(frames[-n:], width, height)
        out = _anchor(positive, vae, frames)
        return (out, n, f"context: {n} frames from the last of {context_images.shape[0]} supplied")


# ---------------------------------------------------------------------------
# 3) Image Batch Extend With Overlap (Loop-friendly)
# ---------------------------------------------------------------------------
def _same_geometry(a, b):
    return a.shape[1:] == b.shape[1:]


# RAM-mode accumulator storage for FlywayImageBatchExtendOverlap, keyed by the
# user-supplied accumulator_id. Lives for the ComfyUI process's lifetime; an
# entry is freed once its Loop finishes (is_last=True) or is force-cleared via
# reset=True. Not used at all when cache_path is set (disk mode uses the folder
# itself as the accumulator instead).
_RAM_IMAGE_ACCUMULATORS = {}


def extend_with_overlap(source, new, overlap, side, mode, tail_frames):
    """Pure-tensor core of the join node. Returns (extended, added, tail, overlap_used)."""
    if new is None or new.shape[0] == 0:
        raise ValueError("Image Batch Extend With Overlap: new_images is empty.")
    if source is None or source.shape[0] == 0:
        extended, added, ov = new, new, 0
    else:
        if not _same_geometry(source, new):
            raise ValueError(
                "Image Batch Extend With Overlap: source_images and new_images must have the same "
                f"height/width/channels (got {tuple(source.shape[1:])} vs {tuple(new.shape[1:])})."
            )
        new = new.to(device=source.device, dtype=source.dtype)
        # Keep at least one new frame, and never overlap more than the source has.
        ov = max(0, min(int(overlap), source.shape[0], new.shape[0] - 1))
        if ov == 0:
            extended, added = torch.cat([source, new], 0), new
        elif mode == "cut":
            if side == "source":
                extended, added = torch.cat([source[:-ov], new], 0), new
            else:
                added = new[ov:]
                extended = torch.cat([source, added], 0)
        else:  # linear_blend / ease_in_out: cross-fade the overlapping frames
            t = (torch.arange(ov, dtype=source.dtype, device=source.device) + 1.0) / (ov + 1.0)
            if mode == "ease_in_out":
                t = t * t * (3.0 - 2.0 * t)
            a = t.view(-1, 1, 1, 1)
            blended = source[-ov:] * (1.0 - a) + new[:ov] * a
            added = new[ov:]
            extended = torch.cat([source[:-ov], blended, added], 0)

    tail = extended[-int(tail_frames):] if int(tail_frames) > 0 else extended
    return extended, added, tail, ov


class FlywayImageBatchExtendOverlap:
    """
    Loop-safe accumulator for stitching a video together clip by clip: dedupes
    `new_images` against what has already accumulated, appends the result, and
    hands back a small `tail_images` window to feed the next iteration's Motion
    Context node - across ALL iterations of a Loop, not just one call.

    Give every run of the Loop a stable `accumulator_id` (any string unique to
    THIS video - e.g. the output filename you're building). The first call for
    an id starts empty automatically; there is no separate "first iteration"
    switch to wire correctly. Every call after that:
      1. dedupes new_images against the accumulator's current tail (`overlap`,
         same trimming rules as before)
      2. appends the deduped part to the accumulator
      3. returns tail_images (a small window) for the next iteration
    Set `is_last=True` on the call that closes the Loop and `extended_images`
    will additionally contain the COMPLETE deduped video - that is the only
    call where the whole thing is materialised, so drive it from the Loop's own
    "last iteration" condition, not every iteration. The accumulator is then
    freed automatically.

    Where the accumulator lives - same mechanism either way, just a different
    home for the data:
      cache_path empty  ->  kept in RAM, keyed by accumulator_id. Freed after
                            is_last=True.
      cache_path set    ->  kept on disk in that folder as numbered PNGs. The
                            folder itself is the accumulator's identity; files
                            are left on disk after is_last=True (your choice to
                            clean up, e.g. once you've encoded the video).

    `reset=True` clears this accumulator (the RAM entry, or the cache_path
    folder) before processing this call - only needed to deliberately restart
    an id/folder you are RE-USING; a new one already starts empty on its own.

    overlap_mode
      cut          new_images side: accumulator + new[overlap:]  (default;
                   keeps already-accumulated frames untouched)
                   source side:     accumulator[:-overlap] + new
      linear_blend / ease_in_out: cross-fade the overlapping frames. The
                   blended frames exist only in extended_images; added_images
                   is still new[overlap:].
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "new_images": ("IMAGE",),
                "accumulator_id": ("STRING", {"default": "", "multiline": False,
                                   "tooltip": "Identifies this video across every iteration of ONE Loop. Reuse the exact same string every iteration; use a different one for a different video. Required when cache_path is empty (RAM mode) so unrelated Loops never collide."}),
                "overlap": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                                    "tooltip": "Frames shared by the end of the accumulator and the start of new_images. 0 = plain concatenation."}),
                "overlap_side": (["new_images", "source"], {"default": "new_images",
                                 "tooltip": "For 'cut': which side gives up the duplicated frames."}),
                "overlap_mode": (["cut", "linear_blend", "ease_in_out"], {"default": "cut"}),
            },
            "optional": {
                "tail_frames": ("INT", {"default": 0, "min": 0, "max": 4096, "step": 1,
                                        "tooltip": "tail_images = last N frames of the accumulator after this call; 0 = same as extended_images."}),
                "is_last": ("BOOLEAN", {"default": False,
                            "tooltip": "True on the call that closes the Loop: extended_images then returns the COMPLETE accumulated video, and the accumulator is freed. Ignored if `total` is set and index reaches it."}),
                "cache_path": ("STRING", {"default": "", "multiline": False,
                              "tooltip": "Empty = accumulate in RAM (freed once the last iteration finishes). Set a folder to accumulate on disk as numbered PNGs instead (kept afterwards)."}),
                "reset": ("BOOLEAN", {"default": False,
                          "tooltip": "True: clear this accumulator before processing this call. Ignored (unnecessary) if `index` is set and equals 0."}),
                "index": ("INT", {"default": -1, "min": -1, "max": 999999, "step": 1,
                          "tooltip": "Wire your Loop's iteration index (0-based) here: index==0 automatically resets this accumulator, so you don't need a separate reset switch. Leave at -1 to ignore and use `reset`/`is_last` manually instead."}),
                "total": ("INT", {"default": -1, "min": -1, "max": 999999, "step": 1,
                          "tooltip": "Wire your Loop's total iteration count here: once index reaches total-1, this call is automatically treated as the last one (extended_images returns the complete video). Needs `index` to also be set; leave at -1 to use `is_last` manually instead."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("extended_images", "added_images", "tail_images", "overlap_used", "total_frames")
    FUNCTION = "extend"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        # Stateful (RAM dict / disk folder) - never let ComfyUI cache-skip a call.
        return float("nan")

    def extend(self, new_images, accumulator_id, overlap, overlap_side, overlap_mode,
               tail_frames=0, is_last=False, cache_path="", reset=False, index=-1, total=-1):
        reset = reset or (index == 0)
        is_last = is_last or (index >= 0 and total > 0 and index >= total - 1)
        cache_path = _norm_dir(cache_path)
        disk = bool(cache_path)

        if disk:
            if reset:
                _clear_images(cache_path)
            need = max(int(overlap), int(tail_frames))
            source = _read_tail_images(cache_path, need)
        else:
            if not accumulator_id:
                raise ValueError(
                    "Image Batch Extend With Overlap: accumulator_id is required when cache_path is empty "
                    "(RAM mode) - otherwise unrelated Loops would share the same accumulator."
                )
            if reset:
                _RAM_IMAGE_ACCUMULATORS.pop(accumulator_id, None)
            source = _RAM_IMAGE_ACCUMULATORS.get(accumulator_id)

        extended, added, tail, ov = extend_with_overlap(
            source, new_images, overlap, overlap_side, overlap_mode, tail_frames
        )

        if disk:
            _save_image_frames(cache_path, added)
            total = len(_list_frames(cache_path))
            extended_out = _load_all_frames(cache_path) if is_last else extended
        else:
            full = torch.cat([source, added], 0) if source is not None else added
            _RAM_IMAGE_ACCUMULATORS[accumulator_id] = full
            total = int(full.shape[0])
            extended_out = full if is_last else extended
            if is_last:
                _RAM_IMAGE_ACCUMULATORS.pop(accumulator_id, None)

        return (extended_out, added, tail, int(ov), int(total))


# ---------------------------------------------------------------------------
# 4) Audio Batch Extend With Overlap (Loop-friendly)
# ---------------------------------------------------------------------------
_AUDIO_EXTS = (".wav", ".flac")


# RAM-mode accumulator storage for FlywayAudioBatchExtendOverlap, mirrors
# _RAM_IMAGE_ACCUMULATORS above.
_RAM_AUDIO_ACCUMULATORS = {}


def _audio_natural_key(name):
    return _natural_key(name)


def _list_audio_chunks(directory):
    d = _norm_dir(directory)
    if not d or not os.path.isdir(d):
        return []
    entries = []
    with os.scandir(d) as it:
        for e in it:
            if e.is_file() and e.name.lower().endswith(_AUDIO_EXTS):
                entries.append(e.path)
    entries.sort(key=lambda p: _audio_natural_key(os.path.basename(p)))
    return entries


def _clear_audio_chunks(directory):
    """Same safety rules as _clear_images, but for the .wav/.flac chunk files this node writes."""
    d = _norm_dir(directory)
    if not d or not os.path.isdir(d):
        return 0
    real = os.path.abspath(d)
    if os.path.dirname(real) == real or os.path.normcase(real) in _protected_dirs():
        raise ValueError(
            f"Audio Batch Extend With Overlap: refusing to clear '{real}' (drive root, home, or ComfyUI input/output root). "
            "Use a dedicated sub-folder."
        )
    removed = 0
    for name in os.listdir(real):
        full = os.path.join(real, name)
        if os.path.isfile(full) and os.path.splitext(name)[1].lower() in _AUDIO_EXTS:
            try:
                os.remove(full)
                removed += 1
            except OSError:
                pass
    return removed


def _save_audio_chunk(directory, waveform, sample_rate):
    """Append one [C, T] float chunk as the next numbered .wav file; returns its sample count."""
    import soundfile as sf
    d = _norm_dir(directory)
    if not d:
        raise ValueError("cache_path is empty.")
    os.makedirs(d, exist_ok=True)
    start = len(_list_audio_chunks(d))
    arr = waveform.detach().cpu().numpy().T  # [C, T] -> [T, C] for soundfile
    sf.write(os.path.join(d, f"chunk_{start:08d}.wav"), arr, int(sample_rate))
    return arr.shape[0]


def _cache_sample_rate(directory):
    """Sample rate of the first cached chunk, or None if the cache is empty."""
    import soundfile as sf
    chunks = _list_audio_chunks(directory)
    if not chunks:
        return None
    return sf.info(chunks[0]).samplerate


def _audio_chunk_infos(directory):
    """soundfile.info() for every cached chunk (cheap header reads, no decoding)."""
    import soundfile as sf
    return [sf.info(p) for p in _list_audio_chunks(directory)]


def _load_all_audio(directory):
    """Read every cached chunk back as one AUDIO dict ({waveform:[1,C,T], sample_rate}), oldest first."""
    import soundfile as sf
    chunks = _list_audio_chunks(directory)
    if not chunks:
        return None
    sr = sf.info(chunks[0]).samplerate
    parts = []
    for p in chunks:
        data, this_sr = sf.read(p, dtype="float32", always_2d=True)  # [T, C]
        if this_sr != sr:
            raise ValueError(f"Audio Batch Extend With Overlap: cached chunk '{p}' is {this_sr} Hz, expected {sr} Hz (cache is corrupt or was mixed with another run).")
        parts.append(torch.from_numpy(data.T))  # [C, T]
    waveform = torch.cat(parts, dim=-1).unsqueeze(0)  # [1, C, T]
    return {"waveform": waveform, "sample_rate": sr}


def _read_tail_audio(directory, need_samples):
    """Read only enough TRAILING chunks to cover need_samples (bounded I/O), or None if empty/need<=0.

    Reads chunk files from the end backwards until enough samples are collected,
    so a Loop never has to load the whole growing track just to dedupe the next
    clip - mirrors _read_tail_images for the audio disk cache.
    """
    import soundfile as sf
    if need_samples <= 0:
        return None
    chunks = _list_audio_chunks(directory)
    if not chunks:
        return None
    sr = sf.info(chunks[0]).samplerate
    collected, total = [], 0
    for p in reversed(chunks):
        data, this_sr = sf.read(p, dtype="float32", always_2d=True)  # [T, C]
        if this_sr != sr:
            raise ValueError(f"Audio Batch Extend With Overlap: cached chunk '{p}' is {this_sr} Hz, expected {sr} Hz (cache is corrupt or was mixed with another run).")
        collected.append(torch.from_numpy(data.T))  # [C, T]
        total += data.shape[0]
        if total >= need_samples:
            break
    collected.reverse()
    waveform = torch.cat(collected, dim=-1).unsqueeze(0)  # [1, C, T]
    if waveform.shape[-1] > need_samples:
        waveform = waveform[..., -need_samples:]
    return {"waveform": waveform, "sample_rate": sr}


def _resample_audio(waveform, orig_sr, new_sr):
    if orig_sr == new_sr:
        return waveform
    import comfy.audio
    return comfy.audio.resample(waveform, orig_sr, new_sr)


def extend_audio_with_overlap(source, new, overlap_samples, side, mode, tail_samples):
    """Pure-tensor core, mirrors extend_with_overlap but on the time axis (last dim) of [B,C,T] audio.

    `new`/`source` are AUDIO dicts ({waveform, sample_rate}) or None. The result's
    sample_rate follows `source` (new is resampled to match, if needed); with no
    source, it follows `new`.
    """
    if new is None or new["waveform"].shape[-1] == 0:
        raise ValueError("Audio Batch Extend With Overlap: new_audio is empty.")
    new_wave, new_sr = new["waveform"], new["sample_rate"]

    if source is None or source["waveform"].shape[-1] == 0:
        extended, added, sr, ov = new_wave, new_wave, new_sr, 0
    else:
        src_wave, sr = source["waveform"], source["sample_rate"]
        new_wave = _resample_audio(new_wave, new_sr, sr).to(device=src_wave.device, dtype=src_wave.dtype)
        if src_wave.shape[:2] != new_wave.shape[:2]:
            raise ValueError(
                "Audio Batch Extend With Overlap: source_audio and new_audio must have the same batch size and "
                f"channel count (got {tuple(src_wave.shape[:2])} vs {tuple(new_wave.shape[:2])})."
            )
        ov = max(0, min(int(overlap_samples), src_wave.shape[-1], new_wave.shape[-1] - 1))
        if ov == 0:
            extended, added = torch.cat([src_wave, new_wave], -1), new_wave
        elif mode == "cut":
            if side == "source":
                extended, added = torch.cat([src_wave[..., :-ov], new_wave], -1), new_wave
            else:
                added = new_wave[..., ov:]
                extended = torch.cat([src_wave, added], -1)
        else:  # equal_power: constant-loudness crossfade, standard for audio
            t = (torch.arange(ov, dtype=src_wave.dtype, device=src_wave.device) + 1.0) / (ov + 1.0)
            fade_out, fade_in = torch.cos(t * (math.pi / 2)), torch.sin(t * (math.pi / 2))
            blended = src_wave[..., -ov:] * fade_out + new_wave[..., :ov] * fade_in
            added = new_wave[..., ov:]
            extended = torch.cat([src_wave[..., :-ov], blended, added], -1)

    tail = extended[..., -int(tail_samples):] if int(tail_samples) > 0 else extended
    return extended, added, tail, sr, ov


class FlywayAudioBatchExtendOverlap:
    """
    Audio counterpart of Image Batch Extend With Overlap - same accumulator
    design, same accumulator_id / is_last / reset semantics, applied to the
    soundtrack. See that node's docstring for the full accumulator model; the
    differences here are purely audio-specific:

    - Overlap and tail are given in SECONDS, not frames, since audio has its
      own sample rate independent of the video's fps. To reuse a video overlap
      value (frames), divide by fps first with a Math node.
    - new_audio is resampled automatically if its sample rate differs from the
      accumulator's; the result always follows the accumulator's rate (or
      new_audio's, on the very first call for this id/folder).
    - As covered separately: unless you have also built a genuine audio Motion
      Context (anchoring the previous clip's audio as an MiniMax H3 audio
      guide), consecutive clips' audio is generated independently and has
      nothing real to deduplicate - use overlap_seconds=0 and treat this node
      as a plain Loop concatenator (with the same optional disk cache as the
      image node). `equal_power` crossfade is still available as a purely
      cosmetic seam-smoother at the clip boundary even with overlap_seconds
      set to a small nonzero value, if the hard cut is audible.

    overlap_mode
      cut          side='new_audio': accumulator + new[overlap:]  (default)
                   side='source':    accumulator[:-overlap] + new
      equal_power: constant-loudness crossfade over the overlap region (avoids
                   the loudness dip a plain linear crossfade would cause).
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "new_audio": ("AUDIO",),
                "accumulator_id": ("STRING", {"default": "", "multiline": False,
                                   "tooltip": "Identifies this track across every iteration of ONE Loop. Reuse the exact same string every iteration; use a different one for a different track. Required when cache_path is empty (RAM mode) so unrelated Loops never collide."}),
                "overlap_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 60.0, "step": 0.01,
                                    "tooltip": "Seconds shared by the end of the accumulator and the start of new_audio. 0 = plain concatenation (the normal setting unless you have a real audio Motion Context)."}),
                "overlap_side": (["new_audio", "source"], {"default": "new_audio",
                                 "tooltip": "For 'cut': which side gives up the duplicated audio."}),
                "overlap_mode": (["cut", "equal_power"], {"default": "cut"}),
            },
            "optional": {
                "tail_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 600.0, "step": 0.01,
                                 "tooltip": "tail_audio = last N seconds of the accumulator after this call; 0 = same as extended_audio."}),
                "is_last": ("BOOLEAN", {"default": False,
                            "tooltip": "True on the call that closes the Loop: extended_audio then returns the COMPLETE accumulated track, and the accumulator is freed. Ignored if `total` is set and index reaches it."}),
                "cache_path": ("STRING", {"default": "", "multiline": False,
                              "tooltip": "Empty = accumulate in RAM (freed once the last iteration finishes). Set a folder to accumulate on disk as numbered .wav chunks instead (kept afterwards)."}),
                "reset": ("BOOLEAN", {"default": False,
                          "tooltip": "True: clear this accumulator before processing this call. Ignored (unnecessary) if `index` is set and equals 0."}),
                "index": ("INT", {"default": -1, "min": -1, "max": 999999, "step": 1,
                          "tooltip": "Wire your Loop's iteration index (0-based) here: index==0 automatically resets this accumulator. Leave at -1 to use `reset`/`is_last` manually instead."}),
                "total": ("INT", {"default": -1, "min": -1, "max": 999999, "step": 1,
                          "tooltip": "Wire your Loop's total iteration count here: once index reaches total-1, this call is automatically treated as the last one. Needs `index` to also be set; leave at -1 to use `is_last` manually instead."}),
            },
        }

    RETURN_TYPES = ("AUDIO", "AUDIO", "AUDIO", "FLOAT", "FLOAT")
    RETURN_NAMES = ("extended_audio", "added_audio", "tail_audio", "overlap_seconds_used", "total_seconds")
    FUNCTION = "extend"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, *args, **kwargs):
        return float("nan")

    def extend(self, new_audio, accumulator_id, overlap_seconds, overlap_side, overlap_mode,
               tail_seconds=0.0, is_last=False, cache_path="", reset=False, index=-1, total=-1):
        reset = reset or (index == 0)
        is_last = is_last or (index >= 0 and total > 0 and index >= total - 1)
        cache_path = _norm_dir(cache_path)
        disk = bool(cache_path)

        if disk:
            if reset:
                _clear_audio_chunks(cache_path)
            rate_for_conversion = _cache_sample_rate(cache_path) or new_audio["sample_rate"]
            need_samples = round(max(overlap_seconds, tail_seconds, 0.0) * rate_for_conversion)
            source = _read_tail_audio(cache_path, need_samples)
        else:
            if not accumulator_id:
                raise ValueError(
                    "Audio Batch Extend With Overlap: accumulator_id is required when cache_path is empty "
                    "(RAM mode) - otherwise unrelated Loops would share the same accumulator."
                )
            if reset:
                _RAM_AUDIO_ACCUMULATORS.pop(accumulator_id, None)
            source = _RAM_AUDIO_ACCUMULATORS.get(accumulator_id)
            rate_for_conversion = (source or new_audio)["sample_rate"]

        overlap_samples = round(overlap_seconds * rate_for_conversion)
        tail_samples = round(tail_seconds * rate_for_conversion)

        extended, added, tail, sr, ov = extend_audio_with_overlap(
            source, new_audio, overlap_samples, overlap_side, overlap_mode, tail_samples
        )

        if disk:
            _save_audio_chunk(cache_path, added[0], sr)
            total_seconds = sum(info.frames / info.samplerate for info in _audio_chunk_infos(cache_path))
            extended_out, sr_out = extended, sr
            if is_last:
                cached = _load_all_audio(cache_path)
                if cached is not None:
                    extended_out, sr_out = cached["waveform"], cached["sample_rate"]
        else:
            full_wave = torch.cat([source["waveform"], added], dim=-1) if source is not None else added
            _RAM_AUDIO_ACCUMULATORS[accumulator_id] = {"waveform": full_wave, "sample_rate": sr}
            total_seconds = full_wave.shape[-1] / sr
            extended_out, sr_out = (full_wave, sr) if is_last else (extended, sr)
            if is_last:
                _RAM_AUDIO_ACCUMULATORS.pop(accumulator_id, None)

        extended_audio = {"waveform": extended_out, "sample_rate": sr_out}
        added_audio = {"waveform": added, "sample_rate": sr}
        tail_audio = {"waveform": tail, "sample_rate": sr}
        return (extended_audio, added_audio, tail_audio, float(ov) / sr if sr else 0.0, float(total_seconds))


NODE_CLASS_MAPPINGS = {
    "FlywayH3MotionContextDir": FlywayH3MotionContextDir,
    "FlywayH3MotionContextImage": FlywayH3MotionContextImage,
    "FlywayImageBatchExtendOverlap": FlywayImageBatchExtendOverlap,
    "FlywayAudioBatchExtendOverlap": FlywayAudioBatchExtendOverlap,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FlywayH3MotionContextDir": "🐦‍🔥 H3 Motion Context (Directory)",
    "FlywayH3MotionContextImage": "🐦‍🔥 H3 Motion Context (Image)",
    "FlywayImageBatchExtendOverlap": "🐦‍🔥 Image Batch Extend With Overlap",
    "FlywayAudioBatchExtendOverlap": "🐦‍🔥 Audio Batch Extend With Overlap",
}
