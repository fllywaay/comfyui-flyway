"""
ComfyUI Flyway Plugin - Batch Image Save To Path
🐦‍🔥 Batch Image Save To Path
(merged in from the former standalone `test-comfyui` plugin)

Batch image save to an arbitrary path, with an explicit clear-or-append
switch, built to survive being called every iteration inside a Loop.

The bug this specifically avoids: several community "save images to path"
nodes, when wired inside a Loop, save correctly on the first iteration but
then keep re-saving that SAME first batch on every later iteration instead
of the current one. That happens because ComfyUI's execution cache decides
the node's inputs "haven't changed" between iterations (some loop
implementations feed back an IMAGE tensor that hashes identically call to
call) and reuses the cached result instead of actually calling the node's
function again. This node's IS_CHANGED always returns NaN, which is never
equal to itself, so ComfyUI can never conclude "nothing changed" and always
re-runs the actual save.
"""
import os
import re

import numpy as np


class BatchImageSaveToPath:
    """
    Saves a batch of IMAGE tensors into save_path.

    clear_before_save:
      - True: delete every existing image file in save_path first, then
        save this batch starting at index 00000.
      - False: leave whatever's already there alone and continue numbering
        after the highest existing index in that folder, so repeated calls
        (e.g. once per loop iteration) pile up instead of overwriting each
        other.

    output_path is just save_path echoed back, so you can feed it straight
    into a "load images from directory" node once a loop finishes.
    """

    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "save_path": (
                    "STRING",
                    {"default": "", "tooltip": "Any directory (created if missing). Can be absolute or relative."},
                ),
                "clear_before_save": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "True: wipe existing images in save_path before saving. False: keep them and append, continuing the numbering.",
                    },
                ),
            },
            "optional": {
                "filename_prefix": ("STRING", {"default": "image"}),
                "file_format": (["png", "jpg", "webp"], {"default": "png"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_path",)
    FUNCTION = "run"
    CATEGORY = "flyway"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, images, save_path, clear_before_save, filename_prefix="image", file_format="png"):
        # Force re-execution every single time, regardless of whether
        # ComfyUI thinks the inputs are identical to a previous call. This
        # is what makes the node safe to use inside a Loop (see module
        # docstring) -- without this, later iterations can silently re-save
        # the first iteration's cached batch instead of the current one.
        return float("nan")

    def run(self, images, save_path, clear_before_save, filename_prefix="image", file_format="png"):
        from PIL import Image

        save_path = (save_path or "").strip()
        if not save_path:
            raise ValueError("BatchImageSaveToPath: save_path is empty.")
        os.makedirs(save_path, exist_ok=True)

        if clear_before_save:
            for name in os.listdir(save_path):
                full = os.path.join(save_path, name)
                if os.path.isfile(full) and os.path.splitext(name)[1].lower() in self._IMAGE_EXTS:
                    try:
                        os.remove(full)
                    except OSError:
                        pass
            start_index = 0
        else:
            start_index = self._find_next_index(save_path, filename_prefix)

        ext = "jpg" if file_format == "jpg" else file_format
        save_kwargs = {"quality": 95} if file_format in ("jpg", "webp") else {}

        batch = images
        if hasattr(batch, "detach"):
            batch = batch.detach().cpu().numpy()
        else:
            batch = np.asarray(batch)

        for i in range(batch.shape[0]):
            arr = np.clip(batch[i] * 255.0, 0, 255).astype(np.uint8)
            img = Image.fromarray(arr)
            if file_format == "jpg" and img.mode == "RGBA":
                img = img.convert("RGB")
            fname = f"{filename_prefix}_{start_index + i:05d}.{ext}"
            img.save(os.path.join(save_path, fname), **save_kwargs)

        return (save_path,)

    def _find_next_index(self, save_path, filename_prefix):
        pattern = re.compile(r"^" + re.escape(filename_prefix) + r"_(\d+)\.\w+$")
        max_idx = -1
        for name in os.listdir(save_path):
            m = pattern.match(name)
            if m:
                idx = int(m.group(1))
                if idx > max_idx:
                    max_idx = idx
        return max_idx + 1


NODE_CLASS_MAPPINGS = {
    "BatchImageSaveToPath": BatchImageSaveToPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BatchImageSaveToPath": "🐦‍🔥 Batch Image Save To Path",
}
