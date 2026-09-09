"""Common V3 nodes: small workflow utilities not tied to a model family.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple, Type, Union

import folder_paths
import node_helpers
import numpy as np
import torch
from comfy_api.latest import io, ui
from PIL import Image, ImageOps, ImageSequence

from .core import MAX_PATH_SEGMENTS, NO_UPSCALE, CropBox, crop_box, is_image_file, join_path, parse_crop, resolve_image_path, tail_start

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


NODES: List[Type[io.ComfyNode]] = [
    ArisuPathBuilder,
    ArisuExtractLastImages,
    ArisuPreviewSaveImage,
    ArisuPreviewSaveImageUpscale,
    ArisuLoadImage,
]
