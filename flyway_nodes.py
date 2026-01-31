"""
ComfyUI Flyway Plugin

包含：
🐦‍🔥 Image List ↔ Directory (鲁棒布尔判断版)
🐦‍🔥 逻辑过滤（布尔输出/任意输入）
🐦‍🔥 多行文本轮询
"""

import os
import glob
import random
import hashlib
import re
import numpy as np
import torch
from PIL import Image
import folder_paths

# 辅助函数：深度校验布尔值，防止外部节点传入字符串导致判断错误
def parse_bool(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        # 排除各种表示“假”的字符串
        return val.strip().lower() not in ("false", "no", "0", "off", "f", "none", "")
    if isinstance(val, (int, float)):
        return bool(val)
    return bool(val)

# ============================================================
# 🐦‍🔥 Image List ↔ Directory
# ============================================================

class ImageListDirectory:
    """
    🐦‍🔥 Image List ↔ Directory
    """
    _session_counters = {}

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
                "any_input": ("*", {}), 
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "INT")
    RETURN_NAMES = ("images", "path", "count")
    FUNCTION = "process"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def process(self, path, clear_directory, filename_prefix, skip_count, max_count, images=None, any_input=None):
        path = os.path.abspath(path)
        os.makedirs(path, exist_ok=True)
        
        # 使用增强版布尔解析，防止外部节点传入 "false" 字符串导致清空失败
        should_clear = parse_bool(clear_directory)

        # ---------- 写入逻辑 ----------
        if images is not None and images.shape[0] > 0:
            if should_clear:
                for f in os.listdir(path):
                    if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".gif")):
                        try: os.remove(os.path.join(path, f))
                        except: pass
                start_index = 0
                self._session_counters[path] = 0
            else:
                if path not in self._session_counters:
                    existing_files = [f for f in os.listdir(path) if f.startswith(filename_prefix)]
                    if existing_files:
                        nums = []
                        for f in existing_files:
                            match = re.search(r'_(\d+)\.[^.]+$', f)
                            if match: nums.append(int(match.group(1)))
                        start_index = max(nums) + 1 if nums else 0
                    else:
                        start_index = 0
                    self._session_counters[path] = start_index
                else:
                    start_index = self._session_counters[path]

            for i in range(images.shape[0]):
                img_tensor = images[i]
                arr = (img_tensor.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
                img = Image.fromarray(arr, "RGB")
                name = f"{filename_prefix}_{start_index + i:05d}.png"
                img.save(os.path.join(path, name), quality=100)

            self._session_counters[path] = start_index + images.shape[0]
            print(f"🐦‍🔥 Flyway Save: 写入成功，当前序号累计至 {self._session_counters[path]}")

        # ---------- 读取逻辑 ----------
        exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tiff", "*.gif")
        files = []
        for ext in exts:
            files.extend(glob.glob(os.path.join(path, ext)))
        files.sort(key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)])

        if skip_count > 0: files = files[skip_count:]
        if max_count > 0: files = files[:max_count]

        image_tensors = []
        for f in files:
            try:
                img = Image.open(f).convert("RGB")
                arr = np.array(img).astype(np.float32) / 255.0
                image_tensors.append(torch.from_numpy(arr).unsqueeze(0))
            except: pass

        if image_tensors:
            return (torch.cat(image_tensors, dim=0), path, len(image_tensors))
        return (torch.zeros((1, 64, 64, 3)), path, 0)


# ============================================================
# 🐦‍🔥 逻辑过滤（布尔输出）
# ============================================================

class ImageBatchLogicFilter:
    """
    🐦‍🔥 逻辑过滤（布尔/条件输出）
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "target_index": ("INT", {"default": 0, "min": 0}),
            },
            "optional": {
                "any_input": ("*", {}), # 接受任意输入，通常是循环 index
            }
        }

    RETURN_TYPES = ("IMAGE", "BOOLEAN")
    RETURN_NAMES = ("IMAGE", "布尔") # 优化显示名称
    FUNCTION = "filter"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def filter(self, images, target_index, any_input=None):
        try:
            # 尝试将 any_input 转换为整数进行对比
            current_val = int(any_input) if any_input is not None else -1
        except:
            current_val = -1

        if current_val == target_index:
            return (images, True)
        else:
            return (torch.zeros((1, 1, 1, 3)), False)


# ============================================================
# 🐦‍🔥 多行文本轮询
# ============================================================

class MultiLineTextInput:
    """
    🐦‍🔥 多行文本轮询
    """
    _state_cache = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": ""}),
                "output_mode": (["sequential", "random", "index"], {"default": "sequential"}),
                "line_index": ("INT", {"default": 0, "min": 0}),
            },
            "optional": {
                "any_input": ("*", {}), 
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("full_text", "line_text", "line_count")
    FUNCTION = "process"
    CATEGORY = "flyway"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    def process(self, text, output_mode, line_index, any_input=None):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        count = len(lines)
        if count == 0: return text, "", 0

        text_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        if text_hash not in self._state_cache:
            self._state_cache[text_hash] = {"seq_cursor": 0, "rnd_indices": [], "rnd_cursor": 0}
        
        state = self._state_cache[text_hash]

        if output_mode == "index":
            selected_line = lines[line_index % count]
        elif output_mode == "sequential":
            idx = state["seq_cursor"] % count
            selected_line = lines[idx]
            state["seq_cursor"] = idx + 1
        else: # random
            if not state["rnd_indices"] or state["rnd_cursor"] >= len(state["rnd_indices"]):
                indices = list(range(count))
                random.shuffle(indices)
                state["rnd_indices"] = indices
                state["rnd_cursor"] = 0
            selected_line = lines[state["rnd_indices"][state["rnd_cursor"]]]
            state["rnd_cursor"] += 1

        return text, selected_line, count

# ============================================================
# 注册
# ============================================================

NODE_CLASS_MAPPINGS = {
    "ImageListDirectory": ImageListDirectory,
    "ImageBatchLogicFilter": ImageBatchLogicFilter,
    "MultiLineTextInput": MultiLineTextInput,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageListDirectory": "🐦‍🔥 Image List ↔ Directory",
    "ImageBatchLogicFilter": "🐦‍🔥 逻辑过滤（布尔/条件输出）",
    "MultiLineTextInput": "🐦‍🔥 多行文本轮询（顺序/随机）",
}