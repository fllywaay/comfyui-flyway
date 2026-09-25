"""Tests for flyway_h3_motion.py without a running ComfyUI (stubs comfy / VAE / latent).

Run:  python_embeded\\python.exe tests\\test_h3_motion.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import time
import types

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

ROOT = tempfile.mkdtemp(prefix="flyway_h3_")
OUT_DIR = os.path.join(ROOT, "comfy_output")
os.makedirs(OUT_DIR)

# ---- stubs -----------------------------------------------------------------
comfy = types.ModuleType("comfy")
comfy_utils = types.ModuleType("comfy.utils")
comfy_utils.common_upscale = lambda s, w, h, m, c: F.interpolate(s, size=(h, w), mode="bilinear", align_corners=False)
comfy.utils = comfy_utils  # the import system does this for real packages
comfy_audio = types.ModuleType("comfy.audio")
comfy_audio.resample = lambda waveform, orig_sr, new_sr: (
    waveform if orig_sr == new_sr else
    F.interpolate(waveform, size=int(round(waveform.shape[-1] * new_sr / orig_sr)), mode="linear", align_corners=False)
)
comfy.audio = comfy_audio
ldm = types.ModuleType("comfy.ldm")
mm = types.ModuleType("comfy.ldm.minimax")
mmm = types.ModuleType("comfy.ldm.minimax.model")
mmm.FRAME_PER_TOKEN = (1, 4, 4, 4, 4)
nh = types.ModuleType("node_helpers")
nh.conditioning_set_values = lambda cond, vals: [[t, {**d, **vals}] for t, d in cond]
fp = types.ModuleType("folder_paths")
fp.get_output_directory = lambda: OUT_DIR
fp.get_input_directory = lambda: os.path.join(ROOT, "comfy_input")
for name, mod in {"comfy": comfy, "comfy.utils": comfy_utils, "comfy.audio": comfy_audio,
                  "comfy.ldm": ldm, "comfy.ldm.minimax": mm, "comfy.ldm.minimax.model": mmm,
                  "node_helpers": nh, "folder_paths": fp}.items():
    sys.modules[name] = mod

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fh3", os.path.join(here, "..", "flyway_h3_motion.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeNested:
    is_nested = True

    def __init__(self, *tensors):
        self.tensors = tensors


class FakeVAE:
    def __init__(self):
        self.seen = None

    def encode(self, frames):
        self.seen = frames
        return torch.zeros(1, 24, 2, frames.shape[1] // 16, frames.shape[2] // 16)


def make_latent(latent_t=37, h=6, w=8):  # 37 tokens = 124 frames, canvas 128x96
    return {"samples": FakeNested(torch.zeros(1, 24, latent_t, h, w), torch.zeros(1, 32, 2, 200))}


def write_frames(d, names, size=(160, 120)):
    os.makedirs(d, exist_ok=True)
    for i, n in enumerate(names):
        Image.fromarray(np.full((size[1], size[0], 3), i, dtype=np.uint8)).save(os.path.join(d, n))


def clip(values, hw=(8, 8)):
    """Constant-colour frames: frame i has every pixel == values[i]."""
    if len(values) == 0:
        return torch.zeros(0, hw[0], hw[1], 3)
    return torch.stack([torch.full((hw[0], hw[1], 3), float(v)) for v in values], 0)


def audio_clip(n, sr=16000, channels=1, value=None, start=0.0):
    """[1, C, n] waveform; each sample's value defaults to a ramp from `start`."""
    if value is not None:
        wave = torch.full((n,), float(value))
    else:
        wave = start + torch.arange(n, dtype=torch.float32)
    return {"waveform": wave.view(1, 1, n).expand(1, channels, n).contiguous(), "sample_rate": sr}


ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


def raises(fn, exc=ValueError, text=""):
    try:
        fn()
    except exc as e:
        return text in str(e)
    return False


try:
    positive = [[torch.zeros(1, 4), {"x": 1}]]
    latent = make_latent()

    # ======================= Directory node ==================================
    D = m.FlywayH3MotionContextDir()
    check("registered ids", set(m.NODE_CLASS_MAPPINGS) == {"FlywayH3MotionContextDir", "FlywayH3MotionContextImage", "FlywayImageBatchExtendOverlap", "FlywayAudioBatchExtendOverlap"})
    nan = m.FlywayH3MotionContextDir.IS_CHANGED(directory="x")
    check("Directory IS_CHANGED is NaN (always re-run)", nan != nan)

    nat = os.path.join(ROOT, "nat")
    write_frames(nat, ["clip_9_.png", "clip_10_.png", "clip_2_.png"])
    check("natural sort", [os.path.basename(p) for p in m._list_frames(nat)] == ["clip_2_.png", "clip_9_.png", "clip_10_.png"])

    pick = m._pick_frame_count
    check("pick 22 of 60", pick(60, 22, 124) == 22)
    check("pick 56 of 60", pick(60, 56, 124) == 56)
    check("pick caps to available", pick(30, 56, 124) == 22)
    check("pick small", pick(10, 22, 124) == 5)
    check("pick single frame", pick(3, 22, 124) == 1)
    check("pick capped by clip", pick(60, 56, 20) == 5)
    check("pick tiny clip", pick(60, 22, 5) == 1)

    out, n, st = D.apply(positive, latent, FakeVAE(), os.path.join(ROOT, "nope"), 22, "name", False)
    check("missing dir skipped", out is positive and n == 0)
    empty = os.path.join(ROOT, "empty")
    os.makedirs(empty)
    out, n, st = D.apply(positive, latent, FakeVAE(), empty, 22, "name", False)
    check("empty dir skipped", out is positive and n == 0 and st.startswith("skipped"))
    out, n, st = D.apply(positive, latent, FakeVAE(), "", 22, "name", False)
    check("blank dir skipped", out is positive and n == 0)

    prev = os.path.join(ROOT, "prev")
    write_frames(prev, [f"clip_{i:05d}_.png" for i in range(1, 61)])
    vae = FakeVAE()
    out, n, st = D.apply(positive, latent, vae, prev, 22, "name", False)
    kf = out[0][1]["minimax_keyframes"]
    check("22 frames, resized to canvas", n == 22 and vae.seen.shape == (22, 96, 128, 3))
    check("anchored at frame 0", len(kf) == 1 and kf[0]["resolved_frame_index"] == 0 and "latent" in kf[0])
    check("last frame is newest file", abs(float(vae.seen[-1].mean()) - 59 / 255) < 1e-3)
    check("original conditioning untouched", "minimax_keyframes" not in positive[0][1] and out[0][1]["x"] == 1)
    pos2 = [[torch.zeros(1, 4), {"minimax_keyframes": [{"resolved_frame_index": -1}]}]]
    out, n, _ = D.apply(pos2, latent, FakeVAE(), prev, 5, "name", False)
    check("existing keyframes kept", len(out[0][1]["minimax_keyframes"]) == 2 and n == 5)

    # ---- clear_directory ----
    check("files still there without clear", len(m._list_frames(prev)) == 60)
    os.makedirs(os.path.join(prev, "sub"))
    write_frames(os.path.join(prev, "sub"), ["keep_00001.png"])
    with open(os.path.join(prev, "notes.txt"), "w") as f:
        f.write("keep me")
    out, n, st = D.apply(positive, latent, FakeVAE(), prev, 22, "name", True)
    check("clear -> this run skipped", out is positive and n == 0 and st.startswith("cleared 60 image(s); skipped"))
    check("clear removed every image", len(m._list_frames(prev)) == 0)
    check("clear kept txt + sub-folder", os.path.isfile(os.path.join(prev, "notes.txt")) and os.path.isfile(os.path.join(prev, "sub", "keep_00001.png")))
    out, n, st = D.apply(positive, latent, FakeVAE(), os.path.join(ROOT, "nope"), 22, "name", True)
    check("clear on missing dir is a no-op", out is positive and st.startswith("cleared 0 image(s)"))
    write_frames(prev, [f"clip_{i:05d}_.png" for i in range(1, 31)])
    out, n, st = D.apply(positive, latent, FakeVAE(), prev, 22, "name", False)
    check("after clear, later iterations read new frames", n == 22)

    # ---- clear safety ----
    write_frames(OUT_DIR, ["a_00001.png"])
    check("refuses ComfyUI output root", raises(lambda: D.apply(positive, latent, FakeVAE(), OUT_DIR, 22, "name", True), text="refusing to clear")
          and os.path.isfile(os.path.join(OUT_DIR, "a_00001.png")))
    check("refuses drive root", raises(lambda: D.apply(positive, latent, FakeVAE(), os.path.abspath(os.sep), 22, "name", True), text="refusing to clear"))
    check("refuses home dir", raises(lambda: D.apply(positive, latent, FakeVAE(), os.path.expanduser("~"), 22, "name", True), text="refusing to clear"))
    check("sub-folder of output is allowed", m._clear_images(os.path.join(OUT_DIR, "h3")) == 0)
    check("bad latent rejected", raises(lambda: D.apply(positive, {"samples": torch.zeros(1, 4, 8, 8)}, FakeVAE(), prev, 22, "name", False), text="AV latent"))

    # ======================= Image node ======================================
    I = m.FlywayH3MotionContextImage()
    out, n, st = I.apply(positive, latent, FakeVAE(), 22, None)
    check("Image: None skipped", out is positive and n == 0)
    out, n, st = I.apply(positive, latent, FakeVAE(), 22, torch.zeros(0, 96, 128, 3))
    check("Image: empty batch skipped", out is positive and n == 0)
    frames = clip(list(range(60)), hw=(120, 160)) / 255.0
    vae = FakeVAE()
    out, n, st = I.apply(positive, latent, vae, 22, frames)
    check("Image: 22 frames resized to canvas", n == 22 and vae.seen.shape == (22, 96, 128, 3))
    check("Image: last frame is last supplied", abs(float(vae.seen[-1].mean()) - 59 / 255) < 1e-3)
    check("Image: anchored at 0", out[0][1]["minimax_keyframes"][0]["resolved_frame_index"] == 0)
    rgba = torch.cat([frames, torch.ones(60, 120, 160, 1)], -1)
    vae = FakeVAE()
    I.apply(positive, latent, vae, 22, rgba)
    check("Image: alpha channel dropped", vae.seen.shape[-1] == 3)
    check("Image: bad input rejected", raises(lambda: I.apply(positive, latent, FakeVAE(), 22, torch.zeros(8, 8, 3)), text="IMAGE batch"))

    # ======================= Image Batch Extend With Overlap (stateful) ======
    X = m.FlywayImageBatchExtendOverlap()

    # --- pure-function core (extend_with_overlap) is unchanged; keep a few checks ---
    new = clip(list(range(100, 110)))
    ext, add, tail, ov = m.extend_with_overlap(None, new, 5, "new_images", "cut", 0)
    check("core: no source passes new through", torch.equal(ext, new) and torch.equal(add, new) and ov == 0)
    src = clip(list(range(30)))
    dup_new = torch.cat([src[-5:], clip(list(range(100, 105)))], 0)
    ext, add, tail, ov = m.extend_with_overlap(src, dup_new, 5, "new_images", "cut", 0)
    check("core: cut/new_images dedupes correctly", ov == 5 and torch.equal(ext[:30], src) and torch.equal(ext[30:], dup_new[5:]))

    # --- RAM mode: accumulator_id required ---
    check("RAM mode requires accumulator_id", raises(lambda: X.extend(new, "", 0, "new_images", "cut"), text="accumulator_id is required"))

    # --- RAM mode: multi-iteration accumulation ---
    id1 = "loop_ram_1"
    c1 = clip(list(range(0, 10)))                       # clip 1: frames 0..9
    c2 = torch.cat([c1[-3:], clip(list(range(20, 27)))], 0)  # clip 2 starts with 3 dup frames from c1's tail
    c3 = torch.cat([torch.cat([c1[-3:], clip(list(range(20, 27)))], 0)[-3:], clip(list(range(30, 37)))], 0)

    ext1, add1, tail1, ov1, tot1 = X.extend(c1, id1, 3, "new_images", "cut", tail_frames=3)
    check("RAM it1: first call passes through, ov=0", ov1 == 0 and torch.equal(ext1, c1) and tot1 == 10)
    check("RAM it1: tail is last 3 frames", tail1.shape[0] == 3 and torch.equal(tail1, c1[-3:]))

    ext2, add2, tail2, ov2, tot2 = X.extend(c2, id1, 3, "new_images", "cut", tail_frames=3)
    check("RAM it2: dedupes 3 frames against accumulator", ov2 == 3 and add2.shape[0] == 7 and tot2 == 17)
    check("RAM it2: extended_images is the full accumulator (RAM mode always holds it all)", ext2.shape[0] == tot2)

    ext3, add3, tail3, ov3, tot3 = X.extend(c3, id1, 3, "new_images", "cut", tail_frames=3, is_last=True)
    check("RAM it3 (is_last): total is correct", tot3 == 24)
    check("RAM it3 (is_last): extended_images is the COMPLETE video", ext3.shape[0] == 24)
    check("RAM it3: accumulator freed after is_last", id1 not in m._RAM_IMAGE_ACCUMULATORS)

    # a fresh call with the same id after is_last starts over (no leftover state)
    ext4, add4, tail4, ov4, tot4 = X.extend(clip(list(range(5))), id1, 3, "new_images", "cut")
    check("RAM: id starts fresh again after being freed", ov4 == 0 and tot4 == 5)
    X.extend(clip(list(range(1))), id1, 0, "new_images", "cut", is_last=True)  # clean up for isolation
    check("cleanup: id1 freed", id1 not in m._RAM_IMAGE_ACCUMULATORS)

    # --- RAM mode: reset ---
    id2 = "loop_ram_reset"
    X.extend(clip(list(range(50))), id2, 0, "new_images", "cut")
    check("reset target has state before reset", id2 in m._RAM_IMAGE_ACCUMULATORS)
    ext, add, tail, ov, tot = X.extend(clip(list(range(9))), id2, 0, "new_images", "cut", reset=True)
    check("reset=True discards prior accumulator", tot == 9)
    X.extend(clip(list(range(1))), id2, 0, "new_images", "cut", is_last=True)

    # --- disk mode: multi-iteration accumulation, no accumulator_id needed ---
    cache = os.path.join(ROOT, "extend_cache")
    d1 = clip(list(range(0, 10)))
    d2 = torch.cat([d1[-4:], clip(list(range(50, 56)))], 0)
    ext1, add1, tail1, ov1, tot1 = X.extend(d1, "", 4, "new_images", "cut", tail_frames=4, cache_path=cache)
    check("disk it1: writes 10 frames", tot1 == 10 and len(m._list_frames(cache)) == 10)
    ext2, add2, tail2, ov2, tot2 = X.extend(d2, "", 4, "new_images", "cut", tail_frames=4, cache_path=cache)
    check("disk it2: dedupes against disk tail", ov2 == 4 and add2.shape[0] == 6 and tot2 == 16)
    check("disk it2: extended (non-final) is small", ext2.shape[0] == 4 + 6)
    d3 = torch.cat([d2[-4:], clip(list(range(60, 67)))], 0)
    ext3, add3, tail3, ov3, tot3 = X.extend(d3, "", 4, "new_images", "cut", tail_frames=4, cache_path=cache, is_last=True)
    check("disk it3 (is_last): full read-back has every frame", ext3.shape[0] == 16 + 7 == tot3)
    check("disk: files remain after is_last (not deleted)", len(m._list_frames(cache)) == tot3)

    # --- disk mode: reset clears the folder ---
    ext, add, tail, ov, tot = X.extend(clip(list(range(3))), "", 0, "new_images", "cut", cache_path=cache, reset=True)
    check("disk reset: folder cleared then rewritten", tot == 3 and len(m._list_frames(cache)) == 3)

    # --- shape / empty-input errors still surface through the node ---
    check("Overlap: shape mismatch rejected via disk source", raises(
        lambda: X.extend(clip([1], hw=(4, 4)), "", 1, "new_images", "cut", cache_path=cache), text="same"))
    check("Overlap: empty new rejected", raises(lambda: X.extend(clip([]), "solo", 0, "new_images", "cut"), text="empty"))

    # --- blend modes still work (core function, exercised through the node) ---
    idb = "loop_blend"
    X.extend(clip([0] * 10), idb, 0, "new_images", "cut")
    ext, add, tail, ov, tot = X.extend(clip([100] * 8), idb, 4, "new_images", "linear_blend")
    mid = ext[-8:-4].mean(dim=(1, 2, 3))
    check("Blend: strictly increasing ramp source->new", bool(torch.all(mid[1:] > mid[:-1])))
    X.extend(clip([0]), idb, 0, "new_images", "cut", is_last=True)

    # ======================= Audio Batch Extend With Overlap (stateful) ======
    A = m.FlywayAudioBatchExtendOverlap()

    check("Audio RAM mode requires accumulator_id", raises(lambda: A.extend(audio_clip(100), "", 0.0, "new_audio", "cut"), text="accumulator_id is required"))

    # --- RAM mode multi-iteration ---
    aid1 = "audio_ram_1"
    ac1 = audio_clip(8000, sr=8000, value=0.1)
    ea1, aa1, ta1, ovu1, tot1 = A.extend(ac1, aid1, 0.0, "new_audio", "cut", tail_seconds=0.25)
    check("Audio RAM it1: first call passes through", ovu1 == 0.0 and tot1 == 1.0 and ta1["waveform"].shape[-1] == 2000)

    # second clip: overlaps 0.5s of the accumulator, resampled from a different rate
    ac2 = audio_clip(8000 + 4000, sr=16000, value=0.2)  # 0.75s new content at 16kHz after resample math below
    ea2, aa2, ta2, ovu2, tot2 = A.extend(ac2, aid1, 0.5, "new_audio", "cut", tail_seconds=0.25)
    check("Audio RAM it2: overlap_seconds_used matches request", abs(ovu2 - 0.5) < 1e-6)
    check("Audio RAM it2: resampled to accumulator's 8kHz rate", ea2["sample_rate"] == 8000)

    ea3, aa3, ta3, ovu3, tot3 = A.extend(audio_clip(4000, sr=8000, value=0.3), aid1, 0.0, "new_audio", "cut", is_last=True)
    check("Audio RAM it3 (is_last): total_seconds matches accumulator length", abs(tot3 - (ea3["waveform"].shape[-1] / ea3["sample_rate"])) < 1e-9)
    check("Audio RAM: accumulator freed after is_last", aid1 not in m._RAM_AUDIO_ACCUMULATORS)

    # --- disk mode multi-iteration ---
    acache = os.path.join(ROOT, "audio_cache")
    b1 = audio_clip(8000, sr=8000, value=0.1)
    ea, aa, ta, ovu, tot = A.extend(b1, "", 0.0, "new_audio", "cut", tail_seconds=0.25, cache_path=acache)
    check("Audio disk it1: writes one chunk", tot == 1.0 and len(m._list_audio_chunks(acache)) == 1)
    b2 = audio_clip(6000, sr=8000, value=0.2)
    ea, aa, ta, ovu, tot = A.extend(b2, "", 0.25, "new_audio", "cut", tail_seconds=0.25, cache_path=acache)
    check("Audio disk it2: dedupe uses bounded tail read from disk", abs(ovu - 0.25) < 1e-6 and abs(tot - (1.0 + 6000 / 8000 - 0.25)) < 1e-6)
    b3 = audio_clip(4000, sr=8000, value=0.3)
    ea3, aa3, ta3, ovu3, tot3 = A.extend(b3, "", 0.0, "new_audio", "cut", cache_path=acache, is_last=True)
    check("Audio disk it3 (is_last): full read-back duration matches total", abs(ea3["waveform"].shape[-1] / ea3["sample_rate"] - tot3) < 1e-6)
    check("Audio disk: chunks remain after is_last", len(m._list_audio_chunks(acache)) == 3)

    # --- disk reset ---
    ea, aa, ta, ovu, tot = A.extend(audio_clip(1000, sr=8000), "", 0.0, "new_audio", "cut", cache_path=acache, reset=True)
    check("Audio disk reset: chunks cleared then rewritten", len(m._list_audio_chunks(acache)) == 1 and abs(tot - 0.125) < 1e-6)

    # --- channel mismatch still rejected ---
    check("Audio: channel mismatch rejected", raises(
        lambda: A.extend(audio_clip(100, sr=8000, channels=2), "", 1.0, "new_audio", "cut", cache_path=acache), text="channel"))

    # --- equal_power crossfade sanity ---
    aidb = "audio_blend"
    A.extend(audio_clip(4000, sr=8000, value=0.0), aidb, 0.0, "new_audio", "cut")
    ea, aa, ta, ovu, tot = A.extend(audio_clip(4000, sr=8000, value=1.0), aidb, 0.1, "new_audio", "equal_power")
    seg = ea["waveform"][0, 0, -4000:-4000 + 800]
    check("Audio equal_power: crossfade ramps from low to high", float(seg[0]) < float(seg[-1]))
    A.extend(audio_clip(1, sr=8000), aidb, 0.0, "new_audio", "cut", is_last=True)

    # ======================= index/total convenience (both nodes) ============
    idx_id = "loop_index_img"
    # index=0 auto-resets even if this id had prior state
    X.extend(clip(list(range(20))), idx_id, 0, "new_images", "cut")
    ext, add, tail, ov, tot = X.extend(clip(list(range(5))), idx_id, 0, "new_images", "cut", index=0, total=3)
    check("Image index=0 auto-resets", tot == 5)
    ext, add, tail, ov, tot = X.extend(clip(list(range(5))), idx_id, 0, "new_images", "cut", index=1, total=3)
    check("Image index=1 (not last): RAM mode still reports correct running total", tot == 10 and ext.shape[0] == tot)
    ext, add, tail, ov, tot = X.extend(clip(list(range(5))), idx_id, 0, "new_images", "cut", index=2, total=3)
    check("Image index==total-1 auto is_last", tot == 15 and ext.shape[0] == 15)
    check("Image: accumulator freed after auto is_last", idx_id not in m._RAM_IMAGE_ACCUMULATORS)
    # explicit is_last still works even without total
    X.extend(clip(list(range(3))), idx_id, 0, "new_images", "cut", index=0)
    ext, add, tail, ov, tot = X.extend(clip(list(range(3))), idx_id, 0, "new_images", "cut", index=1, is_last=True)
    check("Image explicit is_last still honoured without total", tot == 6 and ext.shape[0] == 6)

    aidx_id = "loop_index_audio"
    A.extend(audio_clip(4000, sr=8000), aidx_id, 0.0, "new_audio", "cut")
    ea, aa, ta, ovu, tot = A.extend(audio_clip(4000, sr=8000), aidx_id, 0.0, "new_audio", "cut", index=0, total=2)
    check("Audio index=0 auto-resets", abs(tot - 0.5) < 1e-6)
    ea, aa, ta, ovu, tot = A.extend(audio_clip(4000, sr=8000), aidx_id, 0.0, "new_audio", "cut", index=1, total=2)
    check("Audio index==total-1 auto is_last", abs(tot - 1.0) < 1e-6 and abs(ea["waveform"].shape[-1] / ea["sample_rate"] - 1.0) < 1e-6)
    check("Audio: accumulator freed after auto is_last", aidx_id not in m._RAM_AUDIO_ACCUMULATORS)

finally:
    shutil.rmtree(ROOT, ignore_errors=True)

print("\nALL PASSED" if ok else "\nSOME TESTS FAILED")
sys.exit(0 if ok else 1)
