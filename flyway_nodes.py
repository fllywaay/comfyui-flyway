import os
import glob
import random
import hashlib
import numpy as np
import torch
from PIL import Image
import folder_paths

# ============================================================
# 🐦‍🔥 Image List ↔ Directory
# ============================================================

class ImageListDirectory:
    """
    🐦‍🔥 IMAGE list 与目录交互节点（自动双模式）
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "path": ("STRING", {"default": os.path.join(folder_paths.get_output_directory(), "frames")}),
                "clear_directory": ("BOOLEAN", {"default": True}),
                "filename_prefix": ("STRING", {"default": "frame"}),
                "skip_count": ("INT", {"default": 0, "min": 0}),
                "max_count": ("INT", {"default": 0, "min": 0}),
            },
            "optional": {
                "images": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("images", "path", "count")
    OUTPUT_IS_LIST = (True, False, False)
    FUNCTION = "process"
    CATEGORY = "flyway"

    def process(self, path, clear_directory, filename_prefix, skip_count, max_count, images=None):
        os.makedirs(path, exist_ok=True)
        has_images = images is not None and len(images) > 0

        if has_images:
            if clear_directory:
                for f in os.listdir(path):
                    fp = os.path.join(path, f)
                    if os.path.isfile(fp) and f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".gif")):
                        os.remove(fp)

            existing = [f for f in os.listdir(path) if f.lower().endswith(".png")]
            start_index = len(existing)
            for i, img_tensor in enumerate(images):
                arr = (img_tensor.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
                img = Image.fromarray(arr, "RGB")
                name = f"{filename_prefix}_{start_index + i:05d}.png"
                img.save(os.path.join(path, name))

        exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff", "*.gif")
        files = []
        for ext in exts:
            files.extend(glob.glob(os.path.join(path, ext)))
        files.sort()

        if skip_count > 0: files = files[skip_count:]
        if max_count > 0: files = files[:max_count]

        image_list = []
        for f in files:
            img = Image.open(f).convert("RGB")
            arr = np.array(img).astype(np.float32) / 255.0
            image_list.append(torch.from_numpy(arr).unsqueeze(0))

        if image_list:
            return image_list, path, len(image_list)
        else:
            return [torch.zeros((1, 1, 1, 3))], path, 0


# ============================================================
# 🐦‍🔥 多行文本输入（状态型轮询）
# ============================================================

class MultiLineTextInput:
    """
    🐦‍🔥 多行文本输入

    模式：
    - sequential: 每次执行自动跳到下一行，末尾后回到开头。
    - random: 每次执行随机洗牌一行，全部洗完后重新洗牌。
    - index: 根据输入的 line_index 固定取行。
    """
    
    # 静态缓存，用于跨执行存储当前进度
    _state_cache = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "output_mode": (["sequential", "random", "index"], {"default": "sequential"}),
                "line_index": ("INT", {"default": 0, "min": 0}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("full_text", "line_text", "line_count")
    FUNCTION = "process"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        """
        强制 ComfyUI 在每次点击 Queue 时都认为此节点已改变，
        从而触发 process 函数，实现自动切行。
        """
        return float("NaN")

    def process(self, text, output_mode, line_index):
        # 预处理：去除空行
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        count = len(lines)

        if count == 0:
            return text, "", 0

        # 生成文本指纹，如果文本变了，重置该文本的状态
        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        
        # 初始化状态
        if text_hash not in self._state_cache:
            self._state_cache[text_hash] = {
                "seq_cursor": 0,
                "rnd_shuffled": [],
                "rnd_cursor": 0
            }
        
        state = self._state_cache[text_hash]

        if output_mode == "index":
            # 1. 固定索引模式
            selected_line = lines[line_index % count]
            
        elif output_mode == "sequential":
            # 2. 顺序自动轮询模式
            idx = state["seq_cursor"]
            selected_line = lines[idx % count]
            # 更新下一轮索引
            state["seq_cursor"] = (idx + 1) % count
            
        else: # random 模式
            # 3. 洗牌随机轮询模式
            # 如果随机队列为空或已跑完，重新洗牌
            if not state["rnd_shuffled"] or state["rnd_cursor"] >= len(state["rnd_shuffled"]):
                indices = list(range(count))
                random.shuffle(indices)
                state["rnd_shuffled"] = indices
                state["rnd_cursor"] = 0
            
            idx_in_lines = state["rnd_shuffled"][state["rnd_cursor"]]
            selected_line = lines[idx_in_lines]
            state["rnd_cursor"] += 1

        return text, selected_line, count


# ============================================================
# 注册
# ============================================================

NODE_CLASS_MAPPINGS = {
    "ImageListDirectory": ImageListDirectory,
    "MultiLineTextInput": MultiLineTextInput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageListDirectory": "🐦‍🔥 Image List ↔ Directory",
    "MultiLineTextInput": "🔥 多行文本轮询（顺序/随机）",
}