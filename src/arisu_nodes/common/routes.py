"""The common family's HTTP routes: the save button, and the browse dialog and preview of Load Image (Browse).

Importing this module requires ComfyUI's source tree (aiohttp, ``folder_paths``,
``comfy``, ``comfy_extras``) and torch. The routes are registered from the pack's
``on_load`` in the root ``__init__.py``; request validation, path containment and
directory listing live in ``core.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional

import comfy.model_management
import comfy.utils
import folder_paths
import node_helpers
import numpy as np
import torch
from aiohttp import web
from comfy_extras.nodes_upscale_model import UpscaleModelLoader
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from .core import (
    BROWSE_ROUTE,
    NO_UPSCALE,
    ROOTS_ROUTE,
    SAVE_IMAGE_ROUTE,
    VIEW_ROUTE,
    CropBox,
    SaveRequest,
    browse_directory,
    contained_path,
    crop_box,
    expand_save_prefix,
    image_content_type,
    open_raster_image,
    parse_browse_request,
    parse_save_request,
    parse_view_request,
    preview_file_path,
)
from .paths import image_roots, select_root

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
# Renderings of the view route (``max`` thumbnails, the only resized output, and ``crop`` previews at
# the crop's own size): WEBP, the format /view's own previews use. libwebp's fastest method encodes a
# 3 MP crop in a third of the default's time for the same size at this quality; these are previews.
_RENDER_FORMAT = "WEBP"
_RENDER_QUALITY = 80
_RENDER_METHOD = 0
_SAVE_BODY_LIMIT = 1024 * 1024
_SAVE_LOCK = threading.Lock()
_IMAGE_HEADERS = {"X-Content-Type-Options": "nosniff"}


class UnsupportedImage(ValueError):
    """A file cannot safely be decoded as a raster image."""


def _error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status, headers=_IMAGE_HEADERS)


def _roots() -> Dict[str, str]:
    return image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory())


def register_routes(routes: web.RouteTableDef) -> None:
    """Add the pack's routes to a table; ComfyUI mirrors every route under ``/api``.

    Args:
        routes: ``PromptServer.instance.routes`` in ComfyUI, or a fresh table in tests.
    """
    routes.post(SAVE_IMAGE_ROUTE)(_save_image)
    routes.get(BROWSE_ROUTE)(_browse)
    routes.get(ROOTS_ROUTE)(_list_roots)
    routes.get(VIEW_ROUTE)(_view)


async def _save_image(request: web.Request) -> web.Response:
    """Read bounded JSON and run one save worker, retaining the guard after disconnect."""
    if request.content_type != "application/json":
        return _error("Content-Type must be application/json", 415)
    if request.content_length is not None and request.content_length > _SAVE_BODY_LIMIT:
        return _error("save request exceeds 1 MiB", 413)
    try:
        body = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > _SAVE_BODY_LIMIT:
                return _error("save request exceeds 1 MiB", 413)
        req = parse_save_request(json.loads(body))
        if not _SAVE_LOCK.acquire(blocking=False):
            return _error("another save is still running; try again when it finishes", 429)
        task = asyncio.create_task(asyncio.to_thread(_save_guarded, req))
        # Observe a worker failure even when the request awaiting it was cancelled.
        task.add_done_callback(_observe_save)
        saved = await asyncio.shield(task)
    except FileNotFoundError:
        return _error("preview not found; run the workflow again", 404)
    except UnsupportedImage:
        return _error("preview is not a supported raster image", 415)
    except (TypeError, ValueError, UnicodeError):
        # Decoder/model ValueErrors can contain physical paths too; keep the
        # full diagnostic in the server log, including validation failures.
        logger.warning("Arisu save request rejected", exc_info=True)
        return _error("invalid save request, preview, path or upscale model; see the server log", 400)
    except Exception:
        logger.exception("Arisu save_image failed")
        return _error("saving failed; see the server log", 500)
    return web.json_response({"saved": saved}, headers=_IMAGE_HEADERS)


def _observe_save(task: asyncio.Task[List[Dict[str, str]]]) -> None:
    if not task.cancelled():
        error = task.exception()
        if error is not None and not isinstance(error, (FileNotFoundError, TypeError, ValueError)):
            logger.error("Arisu save worker failed", exc_info=(type(error), error, error.__traceback__))


def _save_guarded(req: SaveRequest) -> List[Dict[str, str]]:
    try:
        return _save(req)
    finally:
        _SAVE_LOCK.release()


async def _list_roots(request: web.Request) -> web.Response:
    """Expose configured root IDs without listing directories or physical paths."""
    try:
        return web.json_response({"roots": [{"id": name, "label": name} for name in _roots()]}, headers=_IMAGE_HEADERS)
    except Exception:
        logger.exception("Arisu roots failed")
        return _error("roots unavailable; see the server log", 500)


async def _browse(request: web.Request) -> web.Response:
    """List a configured root, returning only relative locations."""
    try:
        roots = _roots()
        root = request.query.get("root", "input")
        base = select_root(roots, root)
        req = parse_browse_request(request.query, base)
        listing = await asyncio.to_thread(browse_directory, req.path, base, req.with_tree)
    except (TypeError, ValueError) as error:
        return _error(str(error), 400)
    except (FileNotFoundError, NotADirectoryError):
        return _error("directory not found in the selected root", 404)
    except PermissionError:
        return _error("directory cannot be read", 403)
    except Exception:
        logger.exception("Arisu browse failed")
        return _error("browsing failed; see the server log", 500)
    return web.json_response(
        {
            "root": root,
            "path": listing.path,
            "parent": listing.parent,
            "dirs": list(listing.dirs),
            "files": list(listing.files),
            "ancestors": [{"path": level.path, "dirs": list(level.dirs)} for level in listing.ancestors],
            "roots": [{"id": name, "label": name} for name in roots],
        },
        headers=_IMAGE_HEADERS,
    )


async def _view(request: web.Request) -> web.StreamResponse:
    """Stream the original file as ComfyUI's ``/view`` does, or a WebP rendering when ``max`` or ``crop`` is given.

    Path containment is the boundary: the file is served as it is, under the
    content type of its accepted extension. Decoding happens only for a rendering.
    """
    try:
        base = select_root(_roots(), request.query.get("root", "input"))
        req = parse_view_request(request.query, base)
    except (TypeError, ValueError) as error:
        return _error(str(error), 400)
    content_type = image_content_type(req.path)
    if content_type is None:
        return _error("unsupported image type", 415)
    if not os.path.isfile(req.path):
        return _error("image file not found in the selected root", 404)
    if req.max_size is None and req.crop is None:
        return web.FileResponse(req.path, headers={**_IMAGE_HEADERS, "Content-Type": content_type})
    try:
        body = await asyncio.to_thread(render, req.path, req.max_size, req.crop)
    except FileNotFoundError:
        return _error("image file not found in the selected root", 404)
    except (OSError, ValueError, Image.DecompressionBombError):
        return _error("cannot decode or crop this image", 415)
    except Exception:
        logger.exception("Arisu view failed")
        return _error("rendering failed; see the server log", 500)
    return web.Response(body=body, content_type=f"image/{_RENDER_FORMAT.lower()}", headers=_IMAGE_HEADERS)


def render(path: str, max_size: Optional[int], crop: Optional[CropBox]) -> bytes:
    """The upright first frame of ``path``, cut to ``crop`` and, for a thumbnail, shrunk into ``max_size``, as WEBP.

    The crop applies after the EXIF transpose, as ``nodes._load_image`` applies
    it, so the node preview shows the pixels a run produces, at their own size.
    Only a ``max_size`` thumbnail is ever resized. WEBP refuses a side above
    16383 pixels, which the route reports as an undecodable image.

    Raises:
        ValueError: If the crop lies wholly outside the image.
    """
    with node_helpers.pillow(open_raster_image, path) as image:
        frame = node_helpers.pillow(ImageOps.exif_transpose, image)
        box = crop_box(crop, frame.size) if crop else None
        if box is not None:
            frame = frame.crop(box)
        if max_size is not None:
            frame.thumbnail((max_size, max_size))
        buffer = BytesIO()
        frame.save(buffer, format=_RENDER_FORMAT, quality=_RENDER_QUALITY, method=_RENDER_METHOD)
    return buffer.getvalue()


def _validate_previews(req: SaveRequest):
    """Validate the complete batch and destinations before models or writes."""
    for ref in req.previews:
        source = preview_file_path(folder_paths.get_temp_directory(), ref)
        if not os.path.isfile(source):
            raise FileNotFoundError("preview not found")
        try:
            with Image.open(source, formats=["PNG"]) as image:
                if image.format != "PNG":
                    raise UnsupportedImage("preview must be PNG")
                prefix = expand_save_prefix(req.path, image.width, image.height, datetime.now().astimezone())
                contained_path(folder_paths.get_output_directory(), prefix)
                image.verify()
        except (OSError, Image.DecompressionBombError) as error:
            raise UnsupportedImage("preview cannot be decoded") from error


def _save(req: SaveRequest) -> List[Dict[str, str]]:
    """Validate the batch, optionally upscale it, and exclusively create output PNGs.

    Supported placeholders and metadata match Save Image. Recheck the final
    destination immediately before opening, never following an existing output
    file (including a symlink), and advance the counter on collisions.
    """
    _validate_previews(req)
    upscale = None if req.upscale_model == NO_UPSCALE else model_upscaler(req.upscale_model)
    output_dir = folder_paths.get_output_directory()
    saved: List[Dict[str, str]] = []
    for ref in req.previews:
        source = preview_file_path(folder_paths.get_temp_directory(), ref)
        with Image.open(source, formats=["PNG"]) as png:
            metadata = _copy_metadata(png)
            pixels = png.convert("RGB")
        if upscale is not None:
            pixels = _to_pil(upscale(_to_tensor(pixels)))
        prefix = expand_save_prefix(req.path, pixels.width, pixels.height, datetime.now().astimezone())
        contained_path(output_dir, prefix)
        folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(prefix, output_dir, pixels.width, pixels.height)
        while True:
            file = f"{filename}_{counter:05}_.png"
            relative = os.path.join(subfolder, file)
            # An existing basename is a collision even if it is a dangling symlink.
            target = os.path.join(folder, file)
            if os.path.lexists(target):
                counter += 1
                continue
            target = contained_path(output_dir, relative)
            try:
                with open(target, "xb") as output:
                    pixels.save(output, format="PNG", pnginfo=metadata, compress_level=_COMPRESS_LEVEL)
            except FileExistsError:
                counter += 1
                continue
            break
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
