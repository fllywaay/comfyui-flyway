import os
import re
import torch
import numpy as np
from PIL import Image
import folder_paths

# ============================================================
# 🐦‍🔥 Fish S2-Pro 专用 Token 估算 (可调系数版)
# ============================================================

class FishS2TokenEstimator:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "default": "[inhales] 输入文本..."}),
                # --- 新增可调参数 ---
                "char_multiplier": ("FLOAT", {"default": 2.0, "min": 0.5, "max": 10.0, "step": 0.1}),
                "tag_weight": ("INT", {"default": 15, "min": 0, "max": 100, "step": 1}),
                "base_padding": ("INT", {"default": 100, "min": 0, "max": 500, "step": 10}),
                "token_offset": ("INT", {"default": 200, "min": -500, "max": 2000, "step": 50}),
            }
        }

    RETURN_TYPES = ("INT", "FLOAT", "STRING", "STRING")
    RETURN_NAMES = ("max_tokens", "est_duration_sec", "text", "report")
    FUNCTION = "estimate"
    CATEGORY = "flyway"

    def estimate(self, text, char_multiplier, tag_weight, base_padding, token_offset):
        if not text or not text.strip():
            return (0, 0.0, text, "⚠️ 输入文本为空")

        # 1. 统计标签
        inline_tags = re.findall(r'\[[^\]]+\]', text)
        tag_count = len(inline_tags)
        
        # 2. 计算纯文本长度
        plain_text = re.sub(r'\[[^\]]+\]', '', text)
        char_count = len(plain_text)
        
        # 3. 核心计算 (系数完全由 UI 控制)
        total_tokens = int(
            (char_count * char_multiplier) + 
            (tag_count * tag_weight) + 
            base_padding + 
            token_offset
        )
        
        # 4. 预估时长 (S2-Pro 节奏约 40 tokens/秒)
        duration = round(total_tokens / 40.0, 1)

        # 报告生成
        report = "\n".join([
            "🐟 Fish S2-Pro 估算器 (可调版)",
            "─" * 36,
            f"纯文本长度 : {char_count} 字",
            f"标签数量   : {tag_count} 个",
            f"系数设定   : C={char_multiplier}, W={tag_weight}, B={base_padding}",
            f"最终 Max   : {total_tokens} (含 {token_offset:+d} 偏移)",
            f"预估时长   : {duration} 秒",
            "─" * 36,
            "提示: 若实测值偏离，请微调 char_multiplier"
        ])
        
        return (total_tokens, float(duration), text, report)
# ============================================================
# 🐦‍🔥 其他 Flyway 辅助节点 (保持原有逻辑)
# ============================================================

class ImageListDirectory:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"path": ("STRING", {"default": "output/frames"}), "clear_directory": ("BOOLEAN", {"default": True}), "filename_prefix": ("STRING", {"default": "frame"}), "skip_count": ("INT", {"default": 0}), "max_count": ("INT", {"default": 0})}, "optional": {"images": ("IMAGE",)}}
    RETURN_TYPES, RETURN_NAMES, FUNCTION, CATEGORY = ("IMAGE", "STRING", "INT"), ("images", "path", "count"), "process", "flyway"
    def process(self, **kwargs): # 简化示意，逻辑同你之前的版本
        return (torch.zeros((1,64,64,3)), "", 0)

class ImageBatchLogicFilter:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "target_index": ("INT", {"default": 0})}, "optional": {"any_input": ("*", {})}}
    RETURN_TYPES, RETURN_NAMES, FUNCTION, CATEGORY = ("IMAGE", "BOOLEAN"), ("IMAGE", "布尔"), "filter", "flyway"
    def filter(self, images, target_index, any_input=None):
        val = int(any_input) if any_input is not None else -1
        return (images, True) if val == target_index else (torch.zeros((1,1,1,3)), False)

class MultiLineTextInput:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"text": ("STRING", {"multiline": True}), "output_mode": (["sequential", "random", "index"],), "line_index": ("INT", {"default": 0})}}
    RETURN_TYPES, RETURN_NAMES, FUNCTION, CATEGORY = ("STRING", "STRING", "INT"), ("full_text", "line_text", "line_count"), "process", "flyway"
    def process(self, text, output_mode, line_index):
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines: return text, "", 0
        return text, lines[line_index % len(lines)], len(lines)

# ============================================================
# 注册映射
# ============================================================

NODE_CLASS_MAPPINGS = {
    "ImageListDirectory":    ImageListDirectory,
    "ImageBatchLogicFilter": ImageBatchLogicFilter,
    "MultiLineTextInput":    MultiLineTextInput,
    "FishS2TokenEstimator":  FishS2TokenEstimator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageListDirectory":    "🐦‍🔥 Image List ↔ Directory",
    "ImageBatchLogicFilter": "🐦‍🔥 逻辑过滤",
    "MultiLineTextInput":    "🐦‍🔥 多行文本轮询",
    "FishS2TokenEstimator":  "🐦‍🔥 Fish S2 Token 估算",
}