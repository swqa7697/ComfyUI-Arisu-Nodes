"""The HTTP route behind the Preview & Save Image nodes' save button.

Importing this module requires ComfyUI's source tree (aiohttp, ``folder_paths``,
``comfy``, ``comfy_extras``) and torch. The route is registered from the pack's
``on_load`` in the root ``__init__.py``; request validation and path containment
live in ``core.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, List, Optional

import comfy.model_management
import comfy.utils
import folder_paths
import numpy as np
import torch
from aiohttp import web
from comfy_extras.nodes_upscale_model import UpscaleModelLoader
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .core import NO_UPSCALE, SAVE_IMAGE_ROUTE, SaveRequest, parse_save_request, preview_file_path

logger = logging.getLogger(__name__)

Upscaler = Callable[[torch.Tensor], torch.Tensor]

UPSCALE_MODELS_FOLDER = "upscale_models"
SAVED_FOLDER_TYPE = "output"
# Save Image's PNG compression; the preview was written at level 1 for speed.
_COMPRESS_LEVEL = 4
# Upscale Image (using Model)'s tiling: 512 px tiles with 32 px overlap, halved on out-of-memory down to 128.
_TILE = 512
_MIN_TILE = 128
_OVERLAP = 32


def register_routes(routes: web.RouteTableDef) -> None:
    """Add the pack's routes to a table; ComfyUI mirrors every route under ``/api``.

    Args:
        routes: ``PromptServer.instance.routes`` in ComfyUI, or a fresh table in tests.
    """
    routes.post(SAVE_IMAGE_ROUTE)(_save_image)


async def _save_image(request: web.Request) -> web.Response:
    """Save the previews named in the JSON body; see ``core.parse_save_request`` for the shape.

    The work runs on a worker thread so a multi-second upscale does not stall
    the server's event loop and the progress websocket of a running job.
    """
    try:
        req = parse_save_request(await request.json())
        saved = await asyncio.to_thread(_save, req)
    except FileNotFoundError as error:
        return web.json_response({"error": f"{error}; run the workflow again to refresh the preview"}, status=404)
    except (TypeError, ValueError) as error:
        return web.json_response({"error": str(error)}, status=400)
    except Exception as error:
        logger.exception("Arisu save_image failed")
        return web.json_response({"error": str(error)}, status=500)
    return web.json_response({"saved": saved})


def _save(req: SaveRequest) -> List[Dict[str, str]]:
    upscale = None if req.upscale_model == NO_UPSCALE else model_upscaler(req.upscale_model)
    return save_previews(req, upscale)


def save_previews(req: SaveRequest, upscale: Optional[Upscaler]) -> List[Dict[str, str]]:
    """Copy each preview under the output directory at ``req.path``, upscaling on the way if asked.

    The PNG text chunks of the preview (prompt and workflow) are carried over,
    so the saved file has the metadata Save Image would have written.

    Args:
        req: The validated request.
        upscale: Maps a ``[1, H, W, 3]`` float batch to a larger one, or ``None`` to save as is.

    Returns:
        The saved files as ``{filename, subfolder, type}`` entries, the shape ComfyUI uses for outputs.

    Raises:
        FileNotFoundError: If a preview no longer exists; the temp directory is wiped on restart.
        ValueError: If a preview reference would leave the temp directory.
    """
    temp_dir = folder_paths.get_temp_directory()
    output_dir = folder_paths.get_output_directory()
    saved: List[Dict[str, str]] = []
    for ref in req.previews:
        source = preview_file_path(temp_dir, ref)
        if not os.path.isfile(source):
            raise FileNotFoundError(f"preview {ref.filename} is gone")
        with Image.open(source) as png:
            metadata = _copy_metadata(png)
            pixels = png.convert("RGB")
        if upscale is not None:
            pixels = _to_pil(upscale(_to_tensor(pixels)))
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(req.path, output_dir, pixels.width, pixels.height)
        file = f"{filename}_{counter:05}_.png"
        pixels.save(os.path.join(folder, file), pnginfo=metadata, compress_level=_COMPRESS_LEVEL)
        saved.append({"filename": file, "subfolder": subfolder, "type": SAVED_FOLDER_TYPE})
    return saved


def model_upscaler(model_name: str) -> Upscaler:
    """Load an upscale model and return a function that upscales one ``[B, H, W, 3]`` batch.

    Loading reuses the stock **Load Upscale Model** node. The upscale reproduces
    the pixel path of **Upscale Image (using Model)** with two differences, both
    because it runs from an HTTP request rather than inside the prompt executor:
    no progress bar, since the global progress hook would report to no node and
    consume an interrupt meant for a running job; and no ``load_models_gpu``,
    which edits the executor's loaded-model list without a lock. The model is
    moved to the device for the call and back to the CPU afterwards.

    Args:
        model_name: A file name from ``folder_paths.get_filename_list("upscale_models")``.

    Returns:
        The upscaling function; its output is clamped to ``[0, 1]``.

    Raises:
        ValueError: If ``model_name`` is not an installed upscale model.
    """
    if model_name not in folder_paths.get_filename_list(UPSCALE_MODELS_FOLDER):
        raise ValueError(f"unknown upscale model {model_name!r}")
    model = UpscaleModelLoader.execute(model_name).args[0]
    device = comfy.model_management.get_torch_device()
    # tiled_scale leaves output_device unannotated with a "cpu" default, so a type
    # checker reads it as str; it only reaches Tensor.to(), which takes a device
    # just as well, and the stock upscale node passes one too.
    output_device: Any = comfy.model_management.intermediate_device()

    def upscale(images: torch.Tensor) -> torch.Tensor:
        pixels = images.movedim(-1, -3).to(device)
        tile = _TILE
        model.to(device)
        try:
            with torch.inference_mode():
                while True:
                    try:
                        scaled = comfy.utils.tiled_scale(
                            pixels,
                            lambda a: model(a.float()),
                            tile_x=tile,
                            tile_y=tile,
                            overlap=_OVERLAP,
                            upscale_amount=model.scale,
                            output_device=output_device,
                        )
                        break
                    except Exception as error:
                        comfy.model_management.raise_non_oom(error)
                        tile //= 2
                        if tile < _MIN_TILE:
                            raise
        finally:
            model.to("cpu")
        return torch.clamp(scaled.movedim(-3, -1), min=0.0, max=1.0)

    return upscale


def _copy_metadata(png: Image.Image) -> PngInfo:
    """The PNG text chunks of ``png`` as a ``PngInfo`` for the saved copy; read before ``convert()`` drops them."""
    metadata = PngInfo()
    for key, value in getattr(png, "text", {}).items():
        metadata.add_text(key, value)
    return metadata


def _to_tensor(pixels: Image.Image) -> torch.Tensor:
    """An RGB image as a ``[1, H, W, 3]`` float batch in ``[0, 1]``, the conversion Load Image uses."""
    return torch.from_numpy(np.array(pixels).astype(np.float32) / 255.0)[None]


def _to_pil(images: torch.Tensor) -> Image.Image:
    """The first image of a ``[B, H, W, 3]`` float batch as 8-bit RGB, the conversion Save Image uses."""
    return Image.fromarray(np.clip(255.0 * images[0].cpu().numpy(), 0, 255).astype(np.uint8))
