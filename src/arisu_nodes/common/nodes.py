"""Common V3 nodes: small workflow utilities not tied to a model family.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.
"""

from __future__ import annotations

import json
import logging
import os
import posixpath
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Tuple, Type, Union

import comfy.model_management
import comfy.utils
import folder_paths
import node_helpers
import numpy as np
import torch
from comfy.cli_args import args
from comfy_api.latest import Input, InputImpl, io, ui
from comfy_execution.graph_utils import ExecutionBlocker
from PIL import ImageColor, ImageOps

from .core import (
    CROP_POSITIONS,
    DEFAULT_PAD_COLOR,
    MAX_DIVISIBLE_BY,
    MAX_PATH_SEGMENTS,
    MAX_RESOLUTION,
    NO_UPSCALE,
    PLACEHOLDER_MASK_SIZE,
    RESIZE_METHODS,
    RESIZE_MODES,
    CropBox,
    ResizePlan,
    crop_box,
    is_image_file,
    join_path,
    open_raster_image,
    parse_crop,
    parse_pad_color,
    resize_plan,
    resolve_image_path,
    tail_start,
)
from .paths import image_roots, select_root
from .video import (
    AAC_RATES,
    CODECS,
    COLOR_SPACES,
    EMPTY_EDIT,
    LAYOUTS,
    TAKE_AUDIO,
    director_take_id,
    embedded_samples,
    exact_rate,
    ffmetadata,
    new_take_id,
    parse_edit,
    parse_export_request,
    parse_job,
    parse_take_context,
    resolve_take_prefix,
    take_record,
    take_summary,
    validate_encoding,
    wav_header,
)
from .video_ffmpeg import encode_take_argv
from .video_jobs import count_samples, detect_tools, export_film, feed, log_fallback, probe_path, select_encoder
from .video_store import Reservation, discard_take, publish_take, reserve_take
from .video_worker import write_take

logger = logging.getLogger(__name__)

UPSCALE_MODELS_FOLDER = "upscale_models"
_PATH_TOOLTIP = (
    "Where the save button writes: a filename prefix under ComfyUI's output directory, with Save Image's "
    "filename_prefix rules. 'shots/a' saves output/shots/a_00001_.png; %year%, %width% and the like are expanded; "
    "absolute paths (even inside output) and '..' are refused. External image roots are not save destinations."
)
_LOAD_PATH_TOOLTIP = (
    "The image file relative to the selected configured root ('sub/a.png'), stored by Browse. "
    "Select images with Browse; manual input and wiring are unavailable in the UI. Nothing is uploaded or copied."
)
_LOAD_CROP_TOOLTIP = (
    "An optional crop as left,top,width,height in pixels of the upright image; blank loads the whole image. "
    "The crop button fills it in and the frontend hides it. A box reaching past the image is cut to it."
)
_RESIZE_SIZE_TOOLTIP = "The output {axis} in pixels; 0 takes it from the image (keeping the aspect ratio in resize and pad)."
_RESIZE_METHOD_TOOLTIP = "How pixels are resampled; lanczos is the sharpest for photos, nearest-exact keeps hard edges."
_RESIZE_MODE_TOOLTIP = (
    "crop cuts the image to the aspect ratio of width x height first; pad fits it inside and fills the rest with pad_color; "
    "resize fits it inside width x height; stretch ignores the aspect ratio."
)
_RESIZE_PAD_COLOR_TOOLTIP = "The pad fill: r, g, b (0-255, or 0.0-1.0 with a decimal point), #rrggbb, one grey value, or a colour name."
_RESIZE_POSITION_TOOLTIP = "Where the image stays: the region kept in crop, the side the image sits on in pad."
_RESIZE_GRID_TOOLTIP = "Round the output size down to a multiple of this; 0 or 1 for none. pad snaps the canvas, not the image."
_RESIZE_MASK_TOOLTIP = "Optional; follows the image through the crop, scale and pad. Without it the mask output marks only the padding."


def _segment_inputs() -> List[io.Input]:
    return [
        io.String.Input(
            f"segment_{i}",
            optional=True,
            default="",
            tooltip="One path piece. Blank pieces are skipped; surrounding slashes and spaces are trimmed.",
        )
        for i in range(1, MAX_PATH_SEGMENTS + 1)
    ]


class ArisuPathBuilder(io.ComfyNode):
    """Build a ``/``-joined path from separate text fields.

    Replaces the ``PrimitiveString`` -> ``StringConcatenate`` chains that
    workflows use to assemble a ``filename_prefix`` such as ``minimax_h3/test``.
    The node ships every field; the pack's frontend script shows one and adds
    or removes fields with ``+`` / ``-`` buttons, so the fields a workflow
    does not use never take up space.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema with ``MAX_PATH_SEGMENTS`` optional text fields and one STRING output.
        """
        return io.Schema(
            node_id="ArisuPathBuilder",
            display_name="Path Builder",
            category="Arisu Nodes/Common",
            search_aliases=["prefix", "filename prefix", "join path"],
            description=(
                "Join separate text fields into one path with '/', for filename_prefix inputs and the like. "
                "Blank fields are skipped. Use the + and - buttons to add or remove fields."
            ),
            inputs=_segment_inputs(),
            outputs=[io.String.Output("path", tooltip="The fields joined with '/', blanks skipped.")],
        )

    @classmethod
    def execute(
        cls,
        segment_1: str = "",
        segment_2: str = "",
        segment_3: str = "",
        segment_4: str = "",
        segment_5: str = "",
        segment_6: str = "",
        segment_7: str = "",
        segment_8: str = "",
        segment_9: str = "",
        segment_10: str = "",
        segment_11: str = "",
        segment_12: str = "",
        segment_13: str = "",
        segment_14: str = "",
        segment_15: str = "",
        segment_16: str = "",
    ) -> io.NodeOutput:
        """Join the fields in order.

        Args:
            segment_1: First path piece.
            segment_2: Second path piece; likewise for the remaining fields.
            segment_3: Path piece.
            segment_4: Path piece.
            segment_5: Path piece.
            segment_6: Path piece.
            segment_7: Path piece.
            segment_8: Path piece.
            segment_9: Path piece.
            segment_10: Path piece.
            segment_11: Path piece.
            segment_12: Path piece.
            segment_13: Path piece.
            segment_14: Path piece.
            segment_15: Path piece.
            segment_16: Last path piece.

        Returns:
            The joined path.
        """
        segments = [
            segment_1,
            segment_2,
            segment_3,
            segment_4,
            segment_5,
            segment_6,
            segment_7,
            segment_8,
            segment_9,
            segment_10,
            segment_11,
            segment_12,
            segment_13,
            segment_14,
            segment_15,
            segment_16,
        ]
        return io.NodeOutput(join_path(segments))


class ArisuExtractLastImages(io.ComfyNode):
    """Keep the last ``count`` images of a batch.

    Replaces the count -> subtract -> split chains used to grab the ending
    frame(s) of a decoded video, for previews or as the next clip's keyframe.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema taking an image batch and a count, returning the tail of the batch.
        """
        return io.Schema(
            node_id="ArisuExtractLastImages",
            display_name="Extract Last Images",
            category="Arisu Nodes/Common",
            search_aliases=["extract last frames", "last frames", "last images"],
            description="Keep the last N images of a batch, for example the ending frames of a decoded video.",
            inputs=[
                io.Image.Input("images", tooltip="An image batch, for example the decoded frames of a video."),
                io.Int.Input(
                    "count",
                    default=1,
                    min=1,
                    max=4096,
                    tooltip="How many images to keep from the end of the batch; capped at the batch size.",
                ),
            ],
            outputs=[io.Image.Output("images", tooltip="The last count images, in their original order.")],
        )

    @classmethod
    def execute(cls, images: torch.Tensor, count: int) -> io.NodeOutput:
        """Slice the tail of the batch.

        Args:
            images: Frames shaped ``[B, H, W, C]``.
            count: Number of trailing images to keep.

        Returns:
            A copy of the last ``count`` images, or the whole batch when ``count`` exceeds it.
        """
        return io.NodeOutput(images[tail_start(images.shape[0], count) :].clone())


def _preview_output(images: torch.Tensor, cls: Type[io.ComfyNode], **recorded: str) -> io.NodeOutput:
    """Preview the batch in ComfyUI's temp directory and pass it through unchanged.

    The save button reads ``recorded`` (the run-time widget values) from the
    node's outputs when a widget is fed by a link and so holds no value itself.
    The executor concatenates ui values across list outputs, so each is a list.

    Args:
        images: The batch shaped ``[B, H, W, C]``.
        cls: The executing node class; carries the hidden prompt for the PNG metadata.
        **recorded: Widget values to record next to the preview references.

    Returns:
        The unchanged batch as the first output, with the preview as its ui.
    """
    preview = ui.PreviewImage(images, cls=cls).as_dict()
    preview.update({key: [value] for key, value in recorded.items()})
    return io.NodeOutput(images, ui=preview)


class ArisuPreviewSaveImage(io.ComfyNode):
    """Preview an image batch; save it only when the frontend save button is clicked.

    A run writes nothing but the preview (ComfyUI's temp directory, like
    **Preview Image**). The pack's frontend script adds a ``save`` button that
    posts the preview references to the ``/arisu/save_image`` route, which
    copies them under the output directory at ``path``; no run is queued.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The output-node schema with an image batch, a save path, and the passthrough output.
        """
        return io.Schema(
            node_id="ArisuPreviewSaveImage",
            display_name="Preview & Save Image",
            category="Arisu Nodes/Common",
            search_aliases=["preview save", "save button", "save on click"],
            description=(
                "Preview an image batch and pass it through unchanged. A run saves nothing; the save button writes "
                "the previewed images under ComfyUI's output directory at path, without queueing a run."
            ),
            inputs=[
                io.Image.Input("images", tooltip="The batch to preview; every image in it is saved on click."),
                io.String.Input("path", default="ComfyUI", tooltip=_PATH_TOOLTIP),
            ],
            outputs=[io.Image.Output("images", tooltip="The input batch, unchanged.")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images: torch.Tensor, path: str) -> io.NodeOutput:
        """Preview the batch and pass it through.

        Args:
            images: The batch shaped ``[B, H, W, C]``.
            path: The save prefix, recorded for the button; not written to during the run.

        Returns:
            The unchanged batch, with the preview as ui.
        """
        return _preview_output(images, cls, path=path)


class ArisuPreviewSaveImageUpscale(io.ComfyNode):
    """The preview-and-save node with an optional model upscale applied when saving.

    The upscale happens inside the save request, the way **Upscale Image (using
    Model)** does it; the passthrough output and the preview stay the original
    size, and ``none`` saves the image as is.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema of ``ArisuPreviewSaveImage`` plus the upscale model combo, listing the installed models.
        """
        return io.Schema(
            node_id="ArisuPreviewSaveImageUpscale",
            display_name="Preview & Save Image (Upscale)",
            category="Arisu Nodes/Common",
            search_aliases=["preview save upscale", "save button upscale", "upscale on save"],
            description=(
                "Preview an image batch and pass it through unchanged. A run saves nothing; the save button upscales "
                "the previewed images with the selected model and writes them under ComfyUI's output directory at "
                "path, without queueing a run. Select none to save at the original size."
            ),
            inputs=[
                io.Image.Input("images", tooltip="The batch to preview; every image in it is saved on click."),
                io.String.Input("path", default="ComfyUI", tooltip=_PATH_TOOLTIP),
                io.Combo.Input(
                    "upscale_model",
                    options=[NO_UPSCALE, *folder_paths.get_filename_list(UPSCALE_MODELS_FOLDER)],
                    default=NO_UPSCALE,
                    tooltip="Applied when saving, not during the run; none saves the image at its original size.",
                ),
            ],
            outputs=[io.Image.Output("images", tooltip="The input batch, unchanged.")],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images: torch.Tensor, path: str, upscale_model: str) -> io.NodeOutput:
        """Preview the batch and pass it through; the model is only used by the save button.

        Args:
            images: The batch shaped ``[B, H, W, C]``.
            path: The save prefix, recorded for the button; not written to during the run.
            upscale_model: The model name or ``none``, recorded for the button; not loaded during the run.

        Returns:
            The unchanged batch, with the preview as ui.
        """
        return _preview_output(images, cls, path=path, upscale_model=upscale_model)


def _image_path(path: str, root: str) -> str:
    """Resolve the selected root and refuse non-image or non-regular files."""
    base = select_root(image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory()), root)
    resolved = resolve_image_path(path, base)
    if not os.path.isfile(resolved):
        raise FileNotFoundError("image file not found in the selected root")
    if not is_image_file(resolved):
        raise ValueError("unsupported image type")
    return resolved


def _load_image(path: str, crop: Optional[CropBox]) -> torch.Tensor:
    """Decode an image file the way **Load Image** decodes its pixels, then crop it.

    One static image: an animated file, which Browse never lists, yields its
    first frame, the one the preview shows. An alpha channel is dropped. The
    crop applies after the EXIF transpose, in the pixel space the node preview
    shows; nothing is resized.

    Args:
        path: The absolute path of the file.
        crop: The box to keep, or ``None`` for the whole image.

    Returns:
        The image as ``[1, H, W, 3]``, float32 in ``[0, 1]``.

    Raises:
        ValueError: If the crop lies wholly outside the image.
    """
    with node_helpers.pillow(open_raster_image, path) as file:
        rgb = node_helpers.pillow(ImageOps.exif_transpose, file).convert("RGB")
    box = crop_box(crop, rgb.size) if crop else None
    if box is not None:
        rgb = rgb.crop(box)
    return torch.from_numpy(np.array(rgb).astype(np.float32) / 255.0)[None]


class ArisuLoadImage(io.ComfyNode):
    """Load one static image beneath a configured root, picked through a browse dialog, optionally cropped.

    **Load Image** lists the top level of the input directory and brings other
    files in by copying them there. This node takes a path instead: the pack's
    frontend script adds a ``browse`` button that opens a directory browser
    backed by the ``/arisu/browse`` and ``/arisu/view`` routes, and the picked
    file is read in place at run time. Nothing is uploaded or copied. Browse
    lists static PNG, JPEG, WebP, BMP and AVIF files only. A second button
    opens a crop dialog whose result lands in the hidden ``crop`` input.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema with the path and crop fields and the IMAGE output.
        """
        return io.Schema(
            node_id="ArisuLoadImage",
            display_name="Load Image (Browse)",
            category="Arisu Nodes/Common",
            search_aliases=["load image path", "browse image", "image picker"],
            description=(
                "Load one static image beneath a server-configured directory, selected with Browse, "
                "and optionally cropped in a dialog. Same image output as "
                "Load Image; nothing is uploaded or copied."
            ),
            inputs=[
                io.String.Input("path", default="", socketless=True, tooltip=_LOAD_PATH_TOOLTIP),
                io.String.Input("crop", default="", tooltip=_LOAD_CROP_TOOLTIP),
                io.Combo.Input(
                    "root",
                    options=list(image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory())),
                    default="input",
                    optional=True,
                    socketless=True,
                    tooltip="The image directory selected inside Browse. External roots are set in config.arisu.jsonc.",
                ),
            ],
            outputs=[io.Image.Output("image", tooltip="The image, cropped when a crop is set, as a batch of one.")],
        )

    @classmethod
    def execute(cls, path: str, crop: str = "", root: str = "input") -> io.NodeOutput:
        """Read and decode the file at ``path``, cropped to ``crop`` when one is set.

        Args:
            path: The widget value; see ``core.resolve_image_path`` for the accepted forms.
            crop: The hidden crop widget; see ``core.parse_crop`` for the format.
            root: A server-configured image root ID.

        Returns:
            The image as a batch of one.
        """
        return io.NodeOutput(_load_image(_image_path(path, root), parse_crop(crop)))

    @classmethod
    def validate_inputs(cls, path: Optional[str] = None, crop: Optional[str] = None, root: Optional[str] = "input") -> Union[bool, str]:
        """Check that ``path`` names an existing image file and ``crop`` is well formed before the prompt runs.

        Whether the crop fits the image needs the decoded size, so that is
        checked at run time.

        Args:
            path: The widget value; ``None`` when the input is fed by a link, which
                the executor leaves out of validation.
            crop: The crop widget value, ``None`` likewise.
            root: The configured root ID, ``None`` when linked.

        Returns:
            ``True`` when the file can be loaded, otherwise the error to show.
        """
        try:
            parse_crop(crop)
        except (TypeError, ValueError) as error:
            return str(error)
        try:
            if root is not None:
                select_root(image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory()), root)
            if path is not None and root is not None:
                _image_path(path, root)
        except (OSError, TypeError, ValueError) as error:
            return str(error)
        return True

    @classmethod
    def fingerprint_inputs(cls, path: Optional[str] = None, crop: Optional[str] = None, root: Optional[str] = "input") -> Optional[str]:
        """Change the node's cache key when the file changes on disk.

        The path, size and modification time stand in for a content hash, so a
        large file is not re-read on every queue. The crop needs no part here:
        the cache key already holds every input value.

        Args:
            path: The widget value; ``None`` when fed by a link.
            crop: The crop widget value; unused.
            root: The configured root ID, ``None`` when linked.

        Returns:
            The fingerprint, or ``None`` when there is nothing to fingerprint.
        """
        if path is None or root is None:
            return None
        try:
            resolved = _image_path(path, root)
            stat = os.stat(resolved)
        except (OSError, TypeError, ValueError):
            return path
        return f"{resolved}:{stat.st_mtime_ns}:{stat.st_size}"


def _scale(images: torch.Tensor, size: Tuple[int, int], method: str) -> torch.Tensor:
    """Resample a ``[B, H, W, C]`` batch to ``size`` (``width, height``) with ComfyUI's ``common_upscale``."""
    width, height = size
    return comfy.utils.common_upscale(images.movedim(-1, 1), width, height, method, "disabled").movedim(1, -1)


def _scale_mask(mask: torch.Tensor, size: Tuple[int, int], method: str) -> torch.Tensor:
    """Resample a ``[B, H, W]`` mask to ``size`` the way ``_scale`` resamples the image.

    ``comfy.utils.lanczos`` squeezes a one-channel batch into grey images and
    hands them back without the channel axis, so a lanczos mask travels as
    three equal channels and one comes back.
    """
    width, height = size
    channels = mask.unsqueeze(1)
    if method == "lanczos":
        return comfy.utils.common_upscale(channels.repeat(1, 3, 1, 1), width, height, method, "disabled")[:, 0]
    return comfy.utils.common_upscale(channels, width, height, method, "disabled").squeeze(1)


def _usable_mask(mask: Optional[torch.Tensor], size: Tuple[int, int]) -> Optional[torch.Tensor]:
    """The mask as ``[B, H, W]`` at the image's ``size``, or ``None`` for no mask or ComfyUI's 64x64 placeholder."""
    if mask is None:
        return None
    if mask.ndim == 2:
        mask = mask.unsqueeze(0)
    width, height = size
    placeholder = (PLACEHOLDER_MASK_SIZE, PLACEHOLDER_MASK_SIZE)
    if tuple(mask.shape[-2:]) == placeholder and (height, width) != placeholder:
        return None
    if tuple(mask.shape[-2:]) != (height, width):
        return _scale_mask(mask, size, "bilinear")
    return mask


def _fill_color(value: str, channels: int) -> torch.Tensor:
    """The pad colour as a ``[channels]`` tensor; a colour name goes through Pillow, alpha (a fourth channel) is opaque."""
    rgb = parse_pad_color(value)
    if rgb is None:
        rgb = tuple(channel / 255.0 for channel in ImageColor.getrgb(value.strip())[:3])
    fill = torch.ones(channels)
    fill[: min(3, channels)] = torch.tensor(rgb[: min(3, channels)])
    return fill


def _pad(images: torch.Tensor, plan: ResizePlan, pad_color: str) -> torch.Tensor:
    """Place the scaled batch on the plan's canvas, the rest filled with ``pad_color``."""
    batch, height, width, channels = images.shape
    canvas_width, canvas_height = plan.canvas
    left, top = plan.offset
    canvas = _fill_color(pad_color, channels).to(images.dtype).expand(batch, canvas_height, canvas_width, channels).clone()
    canvas[:, top : top + height, left : left + width] = images
    return canvas


def _pad_mask(mask: Optional[torch.Tensor], plan: ResizePlan, batch: int) -> torch.Tensor:
    """The mask on the plan's canvas: ``1`` over the padding, the scaled mask (or ``0`` without one) under the image."""
    width, height = plan.scaled
    canvas_width, canvas_height = plan.canvas
    left, top = plan.offset
    canvas = torch.ones((batch if mask is None else mask.shape[0], canvas_height, canvas_width), dtype=torch.float32)
    canvas[:, top : top + height, left : left + width] = 0.0 if mask is None else mask
    return canvas


def apply_resize_plan(images: torch.Tensor, plan: ResizePlan, resize_method: str, pad_color: str) -> torch.Tensor:
    """Move a ``[B, H, W, C]`` batch through ``plan``: the crop, the scale, and the pad when the canvas leaves room.

    Args:
        images: The batch to resize.
        plan: The geometry from ``core.resize_plan``.
        resize_method: One of ``RESIZE_METHODS``.
        pad_color: The fill of the ``pad`` mode; see ``core.parse_pad_color``.

    Returns:
        The batch on ``plan.canvas``.
    """
    if plan.crop is not None:
        left, top, crop_width, crop_height = plan.crop
        images = images.narrow(2, left, crop_width).narrow(1, top, crop_height)
    images = _scale(images, plan.scaled, resize_method)
    if plan.canvas != plan.scaled:
        images = _pad(images, plan, pad_color)
    return images


def pad_color_error(mode: Optional[str], pad_color: Optional[str]) -> Optional[str]:
    """The reason ``pad_color`` cannot fill the ``pad`` mode, or ``None`` when it can.

    Args:
        mode: The widget value; ``None`` when fed by a link, which the executor leaves out of validation.
            The colour is only checked when it is ``pad`` or unknown.
        pad_color: Likewise.

    Returns:
        The error to show, or ``None`` when the run can go ahead.
    """
    if pad_color is not None and mode in (None, "pad"):
        try:
            _fill_color(pad_color, 3)
        except (TypeError, ValueError) as error:
            return str(error)
    return None


class ArisuResizeImage(io.ComfyNode):
    """Resize an image batch by cropping, padding, fitting or stretching, with only the size on the node.

    **Upscale Image** stretches to a size or centre-crops to it, so filling a
    canvas takes hand-computed offsets for **Pad Image for Outpainting** and
    landing on a model's pixel grid takes arithmetic in the workflow. This node
    does both, and the options that rarely change (``resize_method``, ``mode``,
    ``pad_color``, ``crop_position``, ``divisible_by``) are
    ordinary inputs that the pack's frontend script hides and edits in a
    settings dialog, leaving ``width`` and ``height`` on the node. The result is
    previewed the way ComfyUI's own **Image Crop** previews it. The geometry is
    ``core.resize_plan``; this class only moves pixels, on the CPU.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The schema with the image, the size, the five settings the frontend hides, the optional mask, and the
            image and mask outputs; ``image`` is the first input and output and ``mask`` the only MASK input, so a
            bypassed node passes each through to its namesake.
        """
        return io.Schema(
            node_id="ArisuResizeImage",
            display_name="Resize Image",
            category="Arisu Nodes/Common",
            search_aliases=["resize image", "scale image", "fit pad crop"],
            description=(
                "Resize an image batch to width x height: cropped, padded, fitted or stretched to the size and snapped to a "
                "pixel grid, with the result shown on the node. The options live behind the settings button; 0 for a "
                "dimension takes it from the image."
            ),
            inputs=[
                io.Image.Input("image", tooltip="The batch to resize; every image gets the same geometry."),
                io.Int.Input("width", default=512, min=0, max=MAX_RESOLUTION, tooltip=_RESIZE_SIZE_TOOLTIP.format(axis="width")),
                io.Int.Input("height", default=512, min=0, max=MAX_RESOLUTION, tooltip=_RESIZE_SIZE_TOOLTIP.format(axis="height")),
                io.Combo.Input("resize_method", options=list(RESIZE_METHODS), default="lanczos", tooltip=_RESIZE_METHOD_TOOLTIP),
                io.Combo.Input("mode", options=list(RESIZE_MODES), default="stretch", tooltip=_RESIZE_MODE_TOOLTIP),
                io.String.Input("pad_color", default=DEFAULT_PAD_COLOR, tooltip=_RESIZE_PAD_COLOR_TOOLTIP),
                io.Combo.Input("crop_position", options=list(CROP_POSITIONS), default="center", tooltip=_RESIZE_POSITION_TOOLTIP),
                io.Int.Input("divisible_by", default=2, min=0, max=MAX_DIVISIBLE_BY, tooltip=_RESIZE_GRID_TOOLTIP),
                io.Mask.Input("mask", optional=True, tooltip=_RESIZE_MASK_TOOLTIP),
            ],
            outputs=[
                io.Image.Output("image", tooltip="The resized batch, exactly width x height after the grid in every mode but resize."),
                io.Mask.Output(
                    "mask", tooltip="The input mask resized alike, 1 over any padding; ComfyUI's 64x64 empty mask when there is neither."
                ),
            ],
            is_output_node=True,
            has_intermediate_output=True,
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        width: int,
        height: int,
        resize_method: str,
        mode: str,
        pad_color: str,
        crop_position: str,
        divisible_by: int,
        mask: Optional[torch.Tensor] = None,
    ) -> io.NodeOutput:
        """Crop, scale and pad the batch as ``core.resize_plan`` says, and preview the result.

        Args:
            image: The batch shaped ``[B, H, W, C]``.
            width: The requested width, ``0`` for "from the image".
            height: The requested height, likewise.
            resize_method: One of ``RESIZE_METHODS``.
            mode: One of ``RESIZE_MODES``.
            pad_color: The fill of the ``pad`` mode; see ``core.parse_pad_color``.
            crop_position: One of ``CROP_POSITIONS``.
            divisible_by: The pixel grid; ``0`` and ``1`` mean none.
            mask: An optional ``[B, H, W]`` mask; a 64x64 placeholder counts as none, another size is fitted to the image.

        Returns:
            The resized batch and its mask, with the batch previewed as ui.
        """
        batch, source_height, source_width, _ = image.shape
        source = (source_width, source_height)
        mask = _usable_mask(mask, source)
        plan = resize_plan(source, width, height, mode, crop_position, divisible_by)
        image = apply_resize_plan(image, plan, resize_method, pad_color)
        if mask is not None and plan.crop is not None:
            left, top, crop_width, crop_height = plan.crop
            mask = mask.narrow(2, left, crop_width).narrow(1, top, crop_height)
        if mask is not None:
            mask = _scale_mask(mask, plan.scaled, resize_method)
        if plan.canvas != plan.scaled:
            mask = _pad_mask(mask, plan, batch)
        if mask is None:
            mask = torch.zeros((1, PLACEHOLDER_MASK_SIZE, PLACEHOLDER_MASK_SIZE))
        return io.NodeOutput(image, mask, ui=ui.PreviewImage(image))

    @classmethod
    def validate_inputs(cls, mode: Optional[str] = None, pad_color: Optional[str] = None) -> Union[bool, str]:
        """Refuse a ``pad_color`` the ``pad`` mode cannot fill with.

        Args:
            mode: The widget value; ``None`` when fed by a link, which the executor leaves out of validation.
                The colour is only checked when it is ``pad`` or unknown.
            pad_color: Likewise.

        Returns:
            ``True`` when the run can go ahead, otherwise the error to show.
        """
        error = pad_color_error(mode, pad_color)
        return True if error is None else error


_FRAME_CHUNK = 16
_SAMPLE_CHUNK = 1 << 20
_PROJECT_TOOLTIP = (
    "The project directory under ComfyUI's output directory, for example the output of Arisu Path Builder. "
    "Takes go to <project>/videos/. Blank uses 'arisu_video'. Absolute paths and '..' are refused."
)
_CODEC_TOOLTIP = "The video codec of the saved MP4. Each encoder has its own CRF scale."
_CRF_TOOLTIP = "Constant quality: lower is better and larger. H.264 and H.265 accept 0-51, AV1 accepts 0-63. Suggested: 18, 20, 24."


def _frame_arrays(images: torch.Tensor, deep: bool) -> Iterator[np.ndarray]:
    """Yield packed RGB frames ``[n, H, W, 3]`` a few at a time, so a long take is never converted in one allocation."""
    for start in range(0, images.shape[0], _FRAME_CHUNK):
        chunk = images[start : start + _FRAME_CHUNK, ..., :3].float()
        if deep:
            yield (chunk * 65535.0).round().clamp(0, 65535).cpu().numpy().astype("<u2")
        else:
            yield (chunk * 255.0).round().clamp(0, 255).to(torch.uint8).cpu().numpy()


def _write_pcm(path: str, waveform: torch.Tensor, rate: int):
    """Write the delivered waveform ``[C, T]`` as interleaved 32-bit float PCM at its native rate and layout."""
    channels, samples = waveform.shape
    with open(path, "xb") as handle:
        handle.write(wav_header(channels, rate, samples))
        handle.writelines(
            waveform[:, start : start + _SAMPLE_CHUNK].T.float().contiguous().cpu().numpy().astype("<f4").tobytes()
            for start in range(0, samples, _SAMPLE_CHUNK)
        )


def _container_tags(cls: Type[io.ComfyNode]) -> Dict[str, str]:
    """The workflow tags stock Save Video embeds, in the same JSON encoding."""
    if args.disable_metadata:
        return {}
    values: Dict[str, Any] = dict(getattr(cls.hidden, "extra_pnginfo", None) or {})
    prompt = getattr(cls.hidden, "prompt", None)
    if prompt is not None:
        values["prompt"] = prompt
    return {key: json.dumps(value) for key, value in values.items()}


class ArisuSaveVideoSegment(io.ComfyNode):
    """Save one rendered segment as a take: a playable MP4, its record and, with sound, float PCM.

    Every run claims a new counter, so an earlier candidate is never replaced. ``take.json`` is published
    last and makes the take visible to **Arisu Assemble Video**; a failed or interrupted run leaves nothing.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The output-node schema with the video, the take location and the encoding choice.
        """
        return io.Schema(
            node_id="ArisuSaveVideoSegment",
            display_name="Save Video Segment",
            category="Arisu Nodes/Common",
            search_aliases=["save video", "save take", "video segment", "save clip"],
            description=(
                "Save a video as a new take under a project: an MP4, a take record and, with sound, the waveform as "
                "float PCM for assembly. Connect it after Create Video."
            ),
            inputs=[
                io.Video.Input("video", tooltip="The delivered segment: its frames and sound are saved as they are."),
                io.String.Input("project_prefix", default="", tooltip=_PROJECT_TOOLTIP),
                io.String.Input("clip_name", default="clip", tooltip="The file name stem inside <project>/videos/."),
                io.Combo.Input("codec", options=list(CODECS), default="h264", tooltip=_CODEC_TOOLTIP),
                io.Int.Input("crf", default=18, min=0, max=63, tooltip=_CRF_TOOLTIP),
                io.String.Input("take_context", default="", socketless=True, tooltip="Set by Director renders; leave blank."),
            ],
            outputs=[io.Video.Output("video", tooltip="The input video, unchanged.")],
            hidden=[io.Hidden.prompt, io.Hidden.extra_pnginfo],
            is_output_node=True,
        )

    @classmethod
    def validate_inputs(
        cls,
        project_prefix: Optional[str] = None,
        clip_name: Optional[str] = None,
        codec: Optional[str] = None,
        crf: Optional[int] = None,
        take_context: Optional[str] = None,
    ) -> Union[bool, str]:
        """Refuse a bad destination or quality before anything upstream runs.

        Args:
            project_prefix: The widget value; ``None`` when fed by a link, which is checked at execution instead.
            clip_name: Likewise.
            codec: Likewise.
            crf: Likewise.
            take_context: Likewise.

        Returns:
            ``True`` when the run can go ahead, otherwise the error to show.
        """
        try:
            if codec is not None and crf is not None:
                validate_encoding(codec, crf)
            context = parse_take_context(take_context if take_context is not None else "")
            if None not in (project_prefix, clip_name):
                resolve_take_prefix(project_prefix, clip_name, 2, 2, datetime.now(), context["take"])
        except (TypeError, ValueError) as error:
            return str(error)
        return True

    @classmethod
    def execute(cls, video: Input.Video, project_prefix: str, clip_name: str, codec: str, crf: int, take_context: str) -> io.NodeOutput:
        """Encode, measure and publish one take.

        Args:
            video: The segment to save.
            project_prefix: The project directory relative to output.
            clip_name: The stem inside ``<project>/videos/``.
            codec: ``h264``, ``h265`` or ``av1``.
            crf: The quality on the selected encoder's scale.
            take_context: Optional Director provenance as JSON.

        Returns:
            The unchanged video, with the stock video preview and the take summary as ui.
        """
        spec = validate_encoding(codec, crf)
        context = parse_take_context(take_context)
        components = video.get_components()
        images = components.images
        frames, height, width = (int(size) for size in images.shape[:3])
        if frames < 1 or width % 2 or height % 2:
            raise ValueError("a take needs at least one frame and an even width and height")
        fps = exact_rate(components.frame_rate)
        waveform = components.audio["waveform"][0] if components.audio else None
        rate = int(components.audio["sample_rate"]) if components.audio else 0
        if waveform is not None and waveform.shape[-1] == 0:
            waveform = None
        if waveform is not None and (waveform.shape[0] not in LAYOUTS or rate not in AAC_RATES):
            raise ValueError("audio must be mono, stereo or 5.1 at a standard sample rate")
        deep = video.get_bit_depth() > 8
        chroma = video.get_chroma_subsampling() or "420"
        if chroma not in spec.chroma:
            logger.warning("%s does not support %s chroma subsampling; saving as 4:2:0", codec, chroma)
            chroma = "420"
        if images.shape[-1] == 4 or components.alpha is not None:
            logger.warning("MP4 takes have no alpha channel; it is discarded")
        pix_fmt = f"yuv{chroma}p" + ("10le" if deep else "")
        color = COLOR_SPACES.get(video.get_color_space() or "sRGB", COLOR_SPACES["sRGB"])
        tools = detect_tools()
        encoder = select_encoder(tools, codec)
        target = resolve_take_prefix(project_prefix, clip_name, width, height, datetime.now(), context["take"])
        reservation = reserve_take(folder_paths.get_output_directory(), target.directory, target.stem)
        try:
            audio_part = reservation.part("audio.wav.part")
            if waveform is not None:
                _write_pcm(audio_part, waveform, rate)
            tags = _container_tags(cls)
            progress = comfy.utils.ProgressBar(frames)

            def chunks() -> Iterator[np.ndarray]:
                for chunk in _frame_arrays(images, deep):
                    yield chunk
                    progress.update(_FRAME_CHUNK)

            limit = embedded_samples(frames, fps, rate, int(waveform.shape[-1])) if waveform is not None else 0
            interrupted = comfy.model_management.throw_exception_if_processing_interrupted
            if tools.ffmpeg is None:
                log_fallback("save", codec)
                write_take(
                    reservation.part("video.part"),
                    chunks(),
                    width=width,
                    height=height,
                    fps=fps,
                    deep=deep,
                    pix_fmt=pix_fmt,
                    color=color,
                    encoder=encoder,
                    crf=crf,
                    waveform=None if waveform is None else waveform.float().cpu().numpy(),
                    rate=rate,
                    limit=limit,
                    tags=tags,
                    check=interrupted,
                )
            else:
                if tags:
                    with open(reservation.part("metadata.part"), "x", encoding="utf-8") as handle:
                        handle.write(ffmetadata(tags))
                feed(
                    encode_take_argv(
                        tools.ffmpeg,
                        width=width,
                        height=height,
                        fps=fps,
                        deep=deep,
                        pix_fmt=pix_fmt,
                        color=color,
                        encoder=encoder,
                        crf=crf,
                        audio=None if waveform is None else (audio_part, limit, int(waveform.shape[0])),
                        metadata=reservation.part("metadata.part") if tags else None,
                        output=reservation.part("video.part"),
                    ),
                    (chunk.tobytes() for chunk in chunks()),
                    interrupted,
                )
            measured = probe_path(reservation.part("video.part"), tools)
            if measured.video is None or measured.video.frames != frames or measured.video.start != 0 or not measured.video.constant:
                raise RuntimeError("the encoded take does not match the delivered frames")
            embedded = count_samples(reservation.part("video.part"), int(waveform.shape[0]), tools) if waveform is not None else 0
            saved = replace(measured.video, codec=spec.probe_name, fps=fps, pix_fmt=pix_fmt, color=("tv", color[2], color[0], color[1]))
            record = publish_take(
                reservation,
                waveform is not None,
                lambda video_path, audio_path: cls._record(
                    reservation,
                    target.directory,
                    target.project,
                    context,
                    saved,
                    encoder,
                    crf,
                    tools.backend,
                    waveform,
                    rate,
                    embedded,
                    audio_path,
                ),
            )
        except BaseException:
            discard_take(reservation)
            raise
        preview = ui.PreviewVideo([ui.SavedResult(reservation.name + ".mp4", target.directory, io.FolderType.output)]).as_dict()
        preview["arisu_take"] = [take_summary(record)]
        return io.NodeOutput(video, ui=preview)

    @classmethod
    def _record(
        cls,
        reservation: Reservation,
        directory: str,
        project: Optional[str],
        context: Dict[str, Optional[str]],
        video: Any,
        encoder: str,
        crf: int,
        backend: str,
        waveform: Optional[torch.Tensor],
        rate: int,
        embedded: int,
        audio_path: Optional[str],
    ) -> Dict[str, Any]:
        """Describe the published video and its optional PCM soundtrack."""
        info = os.stat(reservation.video)
        audio = None
        if waveform is not None and audio_path is not None:
            pcm = os.stat(audio_path)
            audio = {
                "rate": rate,
                "channels": int(waveform.shape[0]),
                "layout": LAYOUTS[int(waveform.shape[0])],
                "samples": int(waveform.shape[-1]),
                "embedded": {"codec": "aac", "samples": embedded, "start": 0},
                "pcm": {
                    "root": "output",
                    "path": posixpath.join(directory, reservation.name + ".arisu", TAKE_AUDIO),
                    "size": pcm.st_size,
                    "format": "f32le",
                },
            }
        return take_record(
            take=director_take_id(directory) or new_take_id(),
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            project=project,
            context=context,
            path=posixpath.join(directory, reservation.name + ".mp4"),
            size=info.st_size,
            video=video,
            encoder=encoder,
            crf=crf,
            audio=audio,
            backend=backend,
        )


class ArisuAssembleVideo(io.ComfyNode):
    """Export the workflow's edit list of saved takes as one film, only when the panel asks for it.

    An ordinary run carries no export request and writes nothing. The panel's Export button queues this
    node alone with a one-shot request ID; that run measures the selected files, plans the picture and
    sample timeline, and publishes ``<project>/exports/<name>_<counter>/`` with the film and its record.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        """Declare the node's id, category, inputs and outputs.

        Returns:
            The output-node schema with the project, the export name, the encoding choice and the hidden edit state.
        """
        return io.Schema(
            node_id="ArisuAssembleVideo",
            display_name="Assemble Video",
            category="Arisu Nodes/Common",
            search_aliases=["assemble video", "edit list", "join clips", "export film", "concatenate video"],
            description=(
                "Select saved takes, order them and export one film on an exact frame and sample timeline. "
                "A run exports nothing; use the panel's Export button."
            ),
            inputs=[
                io.String.Input("project_prefix", default="", tooltip=_PROJECT_TOOLTIP),
                io.String.Input("export_name", default="main", tooltip="Each export creates <project>/exports/<name>_<counter>/."),
                io.Combo.Input(
                    "encoding",
                    options=["inherit", "encode"],
                    default="inherit",
                    tooltip="inherit copies compatible video without loss; encode writes the selected codec and CRF.",
                ),
                io.Combo.Input("codec", options=list(CODECS), default="h264", tooltip=_CODEC_TOOLTIP),
                io.Int.Input("crf", default=18, min=0, max=63, tooltip=_CRF_TOOLTIP),
                io.String.Input("edit_json", default=EMPTY_EDIT, socketless=True, tooltip="The edit list, managed by the panel."),
                io.String.Input("export_request", default="", socketless=True, tooltip="Set by the Export button; leave blank."),
            ],
            outputs=[
                io.Video.Output("video", tooltip="The exported film. Blocked on a run without an export request."),
                io.String.Output("path", tooltip="The film's path relative to ComfyUI's output directory."),
                io.String.Output("record", tooltip="The export record (sequence.json) as text."),
            ],
            is_output_node=True,
        )

    @classmethod
    def validate_inputs(
        cls,
        project_prefix: Optional[str] = None,
        export_name: Optional[str] = None,
        encoding: Optional[str] = None,
        codec: Optional[str] = None,
        crf: Optional[int] = None,
        edit_json: Optional[str] = None,
        export_request: Optional[str] = None,
    ) -> Union[bool, str]:
        """Refuse malformed edit state or settings before anything upstream runs.

        Args:
            project_prefix: The widget value; ``None`` when fed by a link, which is checked at execution instead.
            export_name: Likewise.
            encoding: Likewise.
            codec: Likewise.
            crf: Likewise.
            edit_json: Likewise.
            export_request: Likewise.

        Returns:
            ``True`` when the run can go ahead, otherwise the error to show.
        """
        try:
            if None not in (project_prefix, export_name, encoding, codec, crf):
                parse_export_request(project_prefix, export_name, encoding, codec, crf)
            if edit_json is not None:
                parse_edit(edit_json)
            if export_request is not None:
                parse_job(export_request)
        except (TypeError, ValueError) as error:
            return str(error)
        return True

    @classmethod
    def execute(
        cls, project_prefix: str, export_name: str, encoding: str, codec: str, crf: int, edit_json: str, export_request: str
    ) -> io.NodeOutput:
        """Report the resolved project, and export a film when the run carries an export request.

        Args:
            project_prefix: The project directory relative to output.
            export_name: The export's name inside ``<project>/exports/``.
            encoding: ``inherit`` or ``encode``.
            codec: The target codec when a video encode is needed.
            crf: The quality on that codec's scale.
            edit_json: The edit list document.
            export_request: Blank on an ordinary run, otherwise this export's one-shot ID.

        Returns:
            Blocked outputs and the project on an ordinary run; otherwise the film, its path and its record.
        """
        request = parse_export_request(project_prefix, export_name, encoding, codec, crf)
        document = parse_edit(edit_json)
        job = parse_job(export_request)
        if not job:
            blocked = ExecutionBlocker(None)
            return io.NodeOutput(blocked, blocked, blocked, ui={"arisu_project": [request.project]})
        bar: Dict[str, Any] = {}

        def progress(frame: int, total: int):
            bar.setdefault("bar", comfy.utils.ProgressBar(total)).update_absolute(min(frame, total), total)

        roots = image_roots(folder_paths.get_input_directory(), folder_paths.get_output_directory())
        record = export_film(
            roots, request, document, job, detect_tools(), comfy.model_management.throw_exception_if_processing_interrupted, progress
        )
        film = record["film"]["path"]
        result = ui.PreviewVideo([ui.SavedResult(posixpath.basename(film), posixpath.dirname(film), io.FolderType.output)]).as_dict()
        result["arisu_project"] = [request.project]
        result["arisu_export"] = [
            {
                "request": job,
                "path": film,
                "name": record["name"],
                "counter": record["counter"],
                "frames": record["video"]["frames"],
                "samples": record["audio"]["samples"] if record["audio"] else None,
                "duration": record["video"]["frames"] * record["video"]["fps"][1] / record["video"]["fps"][0],
            }
        ]
        absolute = os.path.join(roots["output"], *film.split("/"))
        return io.NodeOutput(InputImpl.VideoFromFile(absolute), film, json.dumps(record, ensure_ascii=False), ui=result)


NODES: List[Type[io.ComfyNode]] = [
    ArisuPathBuilder,
    ArisuExtractLastImages,
    ArisuPreviewSaveImage,
    ArisuPreviewSaveImageUpscale,
    ArisuLoadImage,
    ArisuResizeImage,
    ArisuSaveVideoSegment,
    ArisuAssembleVideo,
]
