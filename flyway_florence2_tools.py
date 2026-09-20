"""
ComfyUI Flyway Plugin - Florence2 helper nodes
🐦‍🔥 Select Every Nth Image
🐦‍🔥 Florence2 Label Dedup
(merged in from the former standalone `test-comfyui` plugin)

Helpers for turning a video into a de-duplicated object tag list with
kijai's ComfyUI-Florence2: frame down-sampling + label de-duplication.
"""
import json
import re


class AnyType(str):
    """A type string that always compares equal, so this input socket
    will accept a connection from any output type — avoids link
    rejection when a third-party node's output type name doesn't
    exactly match what we expect."""

    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    # Defining __eq__ without __hash__ makes a class unhashable; keep the
    # plain str hash so ComfyUI can still use the type string in sets/dicts.
    __hash__ = str.__hash__


any_type = AnyType("*")


class SelectEveryNthImage:
    """
    Takes an IMAGE batch and an integer N, and returns a new batch
    containing every Nth image (indices 0, N, 2N, ...), recomposed
    back into a single batch tensor. Useful as an explicit, visible
    downsampling step between frame extraction and a per-frame model
    like Florence2.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "n": ("INT", {"default": 1, "min": 1, "max": 10000, "step": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("images", "count")
    FUNCTION = "select"
    CATEGORY = "flyway"

    def select(self, images, n):
        selected = images[::n]
        return (selected, selected.shape[0])


class Florence2LabelDedup:
    """
    Takes the output of a Florence2 node (kijai's ComfyUI-Florence2
    `Florence2Run`) running a detection-style task (e.g. "region_caption",
    which is Florence-2's <OD> object detection, or "dense_region_caption")
    over a batch of video frames, and returns a single de-duplicated,
    comma-separated list of the object labels seen across the whole video.

    Accepts either:
      - the "data" output of Florence2Run (a list with one entry per frame;
        entries that are dicts are searched for a "labels"/"label" key —
        note that for region_caption / dense_region_caption the plugin's
        `data` holds boxes only, no labels), or
      - the "caption" STRING output. For region_caption / dense_region_caption
        this is the raw decoded text with <loc_N> position tokens after each
        label; those tags are stripped here before the labels are split.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "florence2_data": (any_type,),
                "caption_text": ("STRING", {"forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("unique_labels", "unique_count")
    FUNCTION = "dedup"
    CATEGORY = "flyway"

    def _extract_from_data(self, data):
        labels = []

        # data may come through as a python object already, or as a
        # JSON-encoded string depending on node version.
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                return labels

        if isinstance(data, dict):
            data = [data]

        if isinstance(data, (list, tuple)):
            for item in data:
                if isinstance(item, dict):
                    for key in ("labels", "label", "bboxes_labels", "tags"):
                        if key in item and item[key]:
                            vals = item[key]
                            if isinstance(vals, str):
                                labels.append(vals)
                            else:
                                labels.extend([str(v) for v in vals])
                elif isinstance(item, str):
                    labels.append(item)
                elif isinstance(item, (list, tuple)):
                    labels.extend(self._extract_from_data(item))
        return labels

    def _extract_from_caption(self, text):
        if not text:
            return []

        # Florence2Run on a batch returns a list of strings (one per
        # frame) rather than a single joined string - handle both.
        if isinstance(text, (list, tuple)):
            pieces = []
            for t in text:
                pieces.extend(self._extract_from_caption(t))
            return pieces

        if not isinstance(text, str):
            text = str(text)

        # Florence-2 detection output looks like
        #   "person<loc_12><loc_30><loc_200><loc_410>car<loc_...>..."
        # Turn every <...> special token (<loc_N>, <s>, </s>, <pad> ...)
        # into a separator so only the label words are left.
        text = re.sub(r"<[^>]*>", "\n", text)

        pieces = re.split(r"[\n,;]+", text)
        return [p.strip() for p in pieces if p.strip()]

    def dedup(self, florence2_data=None, caption_text=None):
        raw_labels = []

        if florence2_data is not None:
            raw_labels.extend(self._extract_from_data(florence2_data))

        if caption_text:
            raw_labels.extend(self._extract_from_caption(caption_text))

        cleaned = []
        seen = set()
        for label in raw_labels:
            norm = re.sub(r"\s+", " ", label).strip().lower()
            norm = norm.strip(".,;:")
            if not norm:
                continue
            if norm not in seen:
                seen.add(norm)
                cleaned.append(norm)

        cleaned.sort()
        result = ", ".join(cleaned)
        return (result, len(cleaned))


NODE_CLASS_MAPPINGS = {
    "Florence2LabelDedup": Florence2LabelDedup,
    "SelectEveryNthImage": SelectEveryNthImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "Florence2LabelDedup": "🐦‍🔥 Florence2 Label Dedup",
    "SelectEveryNthImage": "🐦‍🔥 Select Every Nth Image",
}
