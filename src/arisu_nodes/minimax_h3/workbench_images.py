"""Shared bounded, lossless image preparation for Workbench attachments."""

from __future__ import annotations

from typing import Any, Dict

from PIL import Image, ImageOps

from .proxy_worker import LimitedOutput

IMAGE_LIMIT = 32 * 1024 * 1024
PROCESSING = {"edge": 4000, "format": "webp", "lossless": True, "sampling": "clip-boundaries-v1", "motion": [2, 4, 6, 8]}


def encode_image(image: Image.Image, output: Any, limit: int = IMAGE_LIMIT) -> Dict[str, int]:
    """Preserve upright pixels and alpha, resize only oversized images, and encode."""
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
    width, height = image.size
    if max(width, height) > PROCESSING["edge"]:
        scale = PROCESSING["edge"] / max(width, height)
        image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
    image.info.clear()
    image.save(LimitedOutput(output, min(limit, IMAGE_LIMIT)), format="WEBP", lossless=True, exact=True, method=4)
    return {"width": image.width, "height": image.height}
