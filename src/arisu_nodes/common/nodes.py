"""Common V3 nodes: small workflow utilities not tied to a model family.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple, Type, Union

import comfy.utils
import folder_paths
import node_helpers
import numpy as np
import torch
from comfy_api.latest import io, ui
from PIL import Image, ImageColor, ImageOps, ImageSequence

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
    parse_crop,
    parse_pad_color,
    resize_plan,
    resolve_image_path,
    tail_start,
)

UPSCALE_MODELS_FOLDER = "upscale_models"
_PATH_TOOLTIP = (
    "Where the save button writes: a filename prefix under ComfyUI's output directory, with Save Image's "
    "filename_prefix rules. 'shots/a' saves output/shots/a_00001_.png; %year%, %width% and the like are expanded; "
    "absolute paths and '..' are refused."
)
_LOAD_PATH_TOOLTIP = (
    "The image file: an absolute path, a ~ path, or a path relative to ComfyUI's input directory ('sub/a.png'). "
    "The browse button fills it in. Nothing is uploaded or copied."
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


def _load_image(path: str, crop: Optional[CropBox]) -> torch.Tensor:
    """Decode an image file the way **Load Image** decodes its pixels, then crop it.

    Every frame of an animated file becomes one image of the batch; frames of
    a different size than the first are skipped. An alpha channel is dropped.
    The crop applies after the EXIF transpose, in the pixel space the node
    preview shows, and identically to every frame; nothing is resized.

    Args:
        path: The absolute path of the file.
        crop: The box to keep, or ``None`` for the whole image.

    Returns:
        The images as ``[B, H, W, 3]``, float32 in ``[0, 1]``.

    Raises:
        ValueError: If the crop lies wholly outside the image.
    """
    images: List[torch.Tensor] = []
    size: Optional[Tuple[int, int]] = None
    box: Optional[Tuple[int, int, int, int]] = None
    with node_helpers.pillow(Image.open, path) as file:
        for raw in ImageSequence.Iterator(file):
            frame = node_helpers.pillow(ImageOps.exif_transpose, raw)
            rgb = frame.convert("RGB")
            if size is None:
                size = rgb.size
                box = crop_box(crop, size) if crop else None
            if rgb.size != size:
                continue
            if box is not None:
                rgb = rgb.crop(box)
            images.append(torch.from_numpy(np.array(rgb).astype(np.float32) / 255.0)[None])
    return torch.cat(images)


class ArisuLoadImage(io.ComfyNode):
    """Load one image from any path on the host, picked through a browse dialog, optionally cropped.

    **Load Image** lists the top level of the input directory and brings other
    files in by copying them there. This node takes a path instead: the pack's
    frontend script adds a ``browse`` button that opens a directory browser
    backed by the ``/arisu/browse`` and ``/arisu/view`` routes, and the picked
    file is read in place at run time. Nothing is uploaded or copied. A second
    button opens a crop dialog whose result lands in the hidden ``crop`` input.
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
                "Load one image from any path on this machine, picked with the browse button or typed: absolute, ~, or "
                "relative to the input directory, and optionally cropped in a dialog. Same file types and image output as "
                "Load Image; nothing is uploaded or copied."
            ),
            inputs=[
                io.String.Input("path", default="", tooltip=_LOAD_PATH_TOOLTIP),
                io.String.Input("crop", default="", tooltip=_LOAD_CROP_TOOLTIP),
            ],
            outputs=[io.Image.Output("image", tooltip="The image, or every frame of an animated file as a batch.")],
        )

    @classmethod
    def execute(cls, path: str, crop: str = "") -> io.NodeOutput:
        """Read and decode the file at ``path``, cropped to ``crop`` when one is set.

        Args:
            path: The widget value; see ``core.resolve_image_path`` for the accepted forms.
            crop: The hidden crop widget; see ``core.parse_crop`` for the format.

        Returns:
            The image batch.
        """
        return io.NodeOutput(_load_image(resolve_image_path(path, folder_paths.get_input_directory()), parse_crop(crop)))

    @classmethod
    def validate_inputs(cls, path: Optional[str] = None, crop: Optional[str] = None) -> Union[bool, str]:
        """Check that ``path`` names an existing image file and ``crop`` is well formed before the prompt runs.

        Whether the crop fits the image needs the decoded size, so that is
        checked at run time.

        Args:
            path: The widget value; ``None`` when the input is fed by a link, which
                the executor leaves out of validation.
            crop: The crop widget value, ``None`` likewise.

        Returns:
            ``True`` when the file can be loaded, otherwise the error to show.
        """
        try:
            parse_crop(crop)
        except (TypeError, ValueError) as error:
            return str(error)
        if path is None:
            return True
        try:
            resolved = resolve_image_path(path, folder_paths.get_input_directory())
        except ValueError as error:
            return str(error)
        if not os.path.isfile(resolved):
            return f"no image file at {resolved}"
        if not is_image_file(resolved):
            return f"not an image file type: {os.path.basename(resolved)}"
        return True

    @classmethod
    def fingerprint_inputs(cls, path: Optional[str] = None, crop: Optional[str] = None) -> Optional[str]:
        """Change the node's cache key when the file changes on disk.

        The path, size and modification time stand in for a content hash, so a
        large file is not re-read on every queue. The crop needs no part here:
        the cache key already holds every input value.

        Args:
            path: The widget value; ``None`` when fed by a link.
            crop: The crop widget value; unused.

        Returns:
            The fingerprint, or ``None`` when there is nothing to fingerprint.
        """
        if path is None:
            return None
        try:
            resolved = resolve_image_path(path, folder_paths.get_input_directory())
            stat = os.stat(resolved)
        except (OSError, ValueError):
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
        if plan.crop is not None:
            left, top, crop_width, crop_height = plan.crop
            image = image.narrow(2, left, crop_width).narrow(1, top, crop_height)
            if mask is not None:
                mask = mask.narrow(2, left, crop_width).narrow(1, top, crop_height)
        image = _scale(image, plan.scaled, resize_method)
        if mask is not None:
            mask = _scale_mask(mask, plan.scaled, resize_method)
        if plan.canvas != plan.scaled:
            image = _pad(image, plan, pad_color)
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
        if pad_color is not None and mode in (None, "pad"):
            try:
                _fill_color(pad_color, 3)
            except (TypeError, ValueError) as error:
                return str(error)
        return True


NODES: List[Type[io.ComfyNode]] = [
    ArisuPathBuilder,
    ArisuExtractLastImages,
    ArisuPreviewSaveImage,
    ArisuPreviewSaveImageUpscale,
    ArisuLoadImage,
    ArisuResizeImage,
]
