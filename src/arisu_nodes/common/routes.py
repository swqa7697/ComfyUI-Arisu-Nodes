"""The common family's HTTP routes: the save button, and the browse dialog and preview of Load Image (Browse).

Importing this module requires ComfyUI's source tree (aiohttp, ``folder_paths``,
``comfy``, ``comfy_extras``) and torch. The routes are registered from the pack's
``on_load`` in the root ``__init__.py``; request validation, path containment and
directory listing live in ``core.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import string
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

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
    SAVE_IMAGE_ROUTE,
    VIEW_ROUTE,
    CropBox,
    DirectoryListing,
    SaveRequest,
    TreeRoot,
    browse_directory,
    crop_box,
    parse_browse_request,
    parse_save_request,
    parse_view_request,
    preview_file_path,
    tree_roots,
)

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
# The browse dialog's thumbnails and the node preview: WEBP, the format /view's own previews use.
_THUMBNAIL_FORMAT = "WEBP"
_THUMBNAIL_QUALITY = 80
# Where the mounted disks come from, per platform: Linux's mount table, macOS's volumes directory.
_LINUX_MOUNTS = "/proc/self/mounts"
_MACOS_VOLUMES = "/Volumes"


def register_routes(routes: web.RouteTableDef) -> None:
    """Add the pack's routes to a table; ComfyUI mirrors every route under ``/api``.

    Args:
        routes: ``PromptServer.instance.routes`` in ComfyUI, or a fresh table in tests.
    """
    routes.post(SAVE_IMAGE_ROUTE)(_save_image)
    routes.get(BROWSE_ROUTE)(_browse)
    routes.get(VIEW_ROUTE)(_view)


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


async def _browse(request: web.Request) -> web.Response:
    """List a directory for the browse dialog; see ``core.browse_directory``.

    Without ``path`` the listing is ComfyUI's input directory. The response
    also carries the tree roots, the input and output places, and the
    ancestor chain (unless ``tree=0``). Directory listing is blocking I/O, so
    it runs on a worker thread.
    """
    req = parse_browse_request(request.query, folder_paths.get_input_directory())
    try:
        roots, listing = await asyncio.to_thread(_browse_tree, req.path, req.with_tree)
    except (FileNotFoundError, NotADirectoryError):
        return web.json_response({"error": f"no such directory: {req.path}"}, status=404)
    except PermissionError:
        return web.json_response({"error": f"permission denied: {req.path}"}, status=403)
    except Exception as error:
        logger.exception("Arisu browse failed")
        return web.json_response({"error": str(error)}, status=500)
    return web.json_response(
        {
            "path": listing.path,
            "parent": listing.parent,
            "dirs": list(listing.dirs),
            "files": list(listing.files),
            "ancestors": [{"path": level.path, "dirs": list(level.dirs)} for level in listing.ancestors],
            "roots": [{"label": root.label, "path": root.path} for root in roots],
            "places": {"input": folder_paths.get_input_directory(), "output": folder_paths.get_output_directory()},
        }
    )


def _browse_tree(path: str, with_tree: bool) -> Tuple[Tuple[TreeRoot, ...], DirectoryListing]:
    """The tree roots and the listing of ``path``, both from blocking I/O."""
    home = os.path.expanduser("~")
    roots = tree_roots(home, _mounts_text(), _volumes(), _drives())
    return roots, browse_directory(path, [root.path for root in roots], home, with_tree)


def _mounts_text() -> Optional[str]:
    """The mount table on Linux, ``None`` where there is none."""
    try:
        with open(_LINUX_MOUNTS, encoding="utf-8", errors="replace") as mounts:
            return mounts.read()
    except OSError:
        return None


def _volumes() -> List[str]:
    """The mounted volumes on macOS other than the boot volume, which is ``/`` itself."""
    try:
        names = os.listdir(_MACOS_VOLUMES)
    except OSError:
        return []
    volumes: List[str] = []
    for name in names:
        volume = os.path.join(_MACOS_VOLUMES, name)
        try:
            if not name.startswith(".") and not os.path.samefile(volume, "/"):
                volumes.append(volume)
        except OSError:
            continue
    return volumes


def _drives() -> List[str]:
    """The drive roots on Windows, none elsewhere."""
    if os.name != "nt":
        return []
    listdrives = getattr(os, "listdrives", None)  # Python 3.12+
    if listdrives is not None:
        return list(listdrives())
    return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]


async def _view(request: web.Request) -> web.StreamResponse:
    """Serve an image file from the host, or a rendering of it when ``max`` or ``crop`` is given.

    Only files whose name passes ComfyUI's image filter are served; see
    ``core.parse_view_request``. Decoding for a rendering runs on a worker thread.
    """
    try:
        req = parse_view_request(request.query)
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)
    if not os.path.isfile(req.path):
        return web.json_response({"error": f"no image file at {req.path}"}, status=404)
    if req.max_size is None and req.crop is None:
        return web.FileResponse(req.path)
    try:
        body = await asyncio.to_thread(render, req.path, req.max_size, req.crop)
    except (OSError, ValueError) as error:  # what Pillow raises for a listed type it cannot decode, SVG for one
        return web.json_response({"error": f"cannot render {os.path.basename(req.path)}: {error}"}, status=415)
    return web.Response(body=body, content_type="image/webp")


def render(path: str, max_size: Optional[int], crop: Optional[CropBox]) -> bytes:
    """The first frame of ``path``, cropped to ``crop`` and downscaled to fit in ``max_size`` pixels, as WEBP.

    The crop applies after the EXIF transpose, as ``nodes._load_image`` applies
    it, so the node preview shows the pixels a run produces. WEBP refuses a
    side above 16383 pixels; the frontend then falls back to a bounded render.

    Args:
        path: An image file.
        max_size: The bound on both sides, or ``None`` to keep the size; a smaller image is not enlarged.
        crop: The box to keep, or ``None`` for the whole image.

    Returns:
        The encoded image.

    Raises:
        ValueError: If the crop lies wholly outside the image.
    """
    with node_helpers.pillow(Image.open, path) as image:
        frame = node_helpers.pillow(ImageOps.exif_transpose, image)
        box = crop_box(crop, frame.size) if crop else None
        if box is not None:
            frame = frame.crop(box)
        if max_size is not None:
            frame.thumbnail((max_size, max_size))
        buffer = BytesIO()
        frame.save(buffer, format=_THUMBNAIL_FORMAT, quality=_THUMBNAIL_QUALITY)
    return buffer.getvalue()


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
