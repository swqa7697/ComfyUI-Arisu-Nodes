"""Fixed CPU-only evaluation of Workbench description and scalar dependencies."""

from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from ..common.core import join_path
from .core import ASPECT_RATIO_LABELS, VideoSettings, canvas_from_megapixels, frames_for_duration, scaled_canvas
from .media import build_bundle


def context_inputs(
    graph: Dict[str, Any], node_id: str, roots: Dict[str, str], names: Tuple[str, ...] = ("video_settings", "resources")
) -> Dict[str, Any]:
    """Resolve only supported descriptions and scalars, never arbitrary node code."""
    memo: Dict[str, Tuple[Any, ...]] = {}
    visiting = set()

    def resolve(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        if len(value) != 2 or not isinstance(value[0], str) or type(value[1]) is not int or value[1] < 0:
            raise ValueError("invalid context link")
        key, slot = value
        if key in visiting or key not in graph:
            raise ValueError("cyclic or missing context dependency")
        if key not in memo:
            visiting.add(key)
            entry = graph[key]
            kind = entry["class_type"]
            inputs = {name: resolve(item) for name, item in entry["inputs"].items()}
            if kind in ("PrimitiveNode", "PrimitiveInt", "PrimitiveFloat", "PrimitiveString"):
                result = (inputs["value"],)
            elif kind == "Reroute":
                if len(inputs) != 1:
                    raise ValueError("invalid context reroute")
                result = tuple(inputs.values())
            elif kind == "StringConcatenate":
                result = (inputs.get("delimiter", "").join((inputs["string_a"], inputs["string_b"])),)
            elif kind == "ArisuPathBuilder":
                result = (join_path([inputs.get("segment_" + str(i), "") for i in range(1, 17)]),)
            elif kind in ("ArisuMiniMaxH3VideoSettings", "ArisuMiniMaxH3VideoSettingsUpscale"):
                for name, low, high in (("megapixels", 0.1, 16), ("duration", 0.2, 150), ("upscale_factor", 1, 8)):
                    if name == "upscale_factor" and not kind.endswith("Upscale"):
                        continue
                    number = inputs.get(name)
                    if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
                        raise ValueError("invalid video setting: " + name)
                width, height = canvas_from_megapixels(inputs["aspect_ratio"], inputs["megapixels"])
                length = frames_for_duration(inputs["duration"])
                ratio = inputs["aspect_ratio"]
                if kind.endswith("Upscale"):
                    factor = inputs["upscale_factor"]
                    tw, th = scaled_canvas(width, height, factor)
                    result = (VideoSettings(width, height, length, ratio, factor, tw, th), width, height, length, factor, tw, th, ratio)
                else:
                    result = (VideoSettings(width, height, length, ratio), width, height, length, ratio)
            elif kind == "ArisuMiniMaxH3ResourceStudio":
                if inputs["aspect_ratio"] not in ASPECT_RATIO_LABELS:
                    raise ValueError("invalid resource aspect ratio")
                result = (build_bundle(roots, inputs["resources_json"], inputs["aspect_ratio"]),)
            else:
                raise ValueError("unsupported CPU context dependency")
            if any(isinstance(item, str) and len(item) > 1024 * 1024 for item in result):
                raise ValueError("context text is too large")
            memo[key] = result
            visiting.remove(key)
        if slot >= len(memo[key]):
            raise ValueError("invalid context output slot")
        return memo[key][slot]

    return {name: resolve(value) for name, value in graph[node_id]["inputs"].items() if name in names}
