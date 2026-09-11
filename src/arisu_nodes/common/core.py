"""ComfyUI-free logic for the common node family.

Everything here imports only the standard library so it can be unit-tested in
the project's own environment, without torch or ComfyUI on the path.
"""

from __future__ import annotations

import math
import mimetypes
import ntpath
import os
import os.path
import posixpath
import re
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MAX_PATH_SEGMENTS = 16
PATH_SEPARATOR = "/"
_SEGMENT_TRIM = string.whitespace + PATH_SEPARATOR

# The Preview & Save Image nodes: the "none" entry of the upscale model combo,
# the route the frontend save button posts to, and the only folder type a
# preview is ever read from (ComfyUI's PreviewImage writes to the temp dir).
NO_UPSCALE = "none"
SAVE_IMAGE_ROUTE = "/arisu/save_image"
PREVIEW_FOLDER_TYPE = "temp"
_PREVIEW_KEYS = ("filename", "subfolder", "type")

# Load Image (Browse): the routes behind the browse dialog and the node preview,
# the MIME major type ComfyUI's image loaders list, and the thumbnail bounds.
BROWSE_ROUTE = "/arisu/browse"
VIEW_ROUTE = "/arisu/view"
IMAGE_CONTENT_TYPE = "image"
MIN_THUMBNAIL = 16
MAX_THUMBNAIL = 4096
# The crop widget: ``left,top,width,height`` in pixels, blank for the whole image.
CROP_SEPARATOR = ","
CROP_FORMAT_ERROR = "crop must be left,top,width,height in pixels"
# Resize Image: the option lists its settings dialog shows (the resampling methods ComfyUI's own upscalers offer),
# the size bounds, the ``[1, 64, 64]`` zeros ComfyUI's loaders emit for "no mask", and the pad colour forms.
RESIZE_METHODS = ("nearest-exact", "bilinear", "area", "bicubic", "lanczos")
RESIZE_MODES = ("crop", "pad", "resize", "stretch")
CROP_POSITIONS = ("center", "top", "bottom", "left", "right")
MAX_RESOLUTION = 16384
MAX_DIVISIBLE_BY = 512
PLACEHOLDER_MASK_SIZE = 64
DEFAULT_PAD_COLOR = "0, 0, 0"
PAD_COLOR_FORMAT_ERROR = "pad_color must be r, g, b (0-255, or 0.0-1.0 with a decimal point), #rrggbb, one grey value, or a colour name"
_HEX_COLOR = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_COLOR_NAME = re.compile(r"[A-Za-z]+$")


@dataclass(frozen=True)
class PreviewRef:
    """One preview file as ComfyUI reports it to the frontend (``{filename, subfolder, type}``)."""

    filename: str
    subfolder: str
    type: str


@dataclass(frozen=True)
class SaveRequest:
    """A validated save-button request: which previews to save, where, and through which model."""

    previews: Tuple[PreviewRef, ...]
    path: str
    upscale_model: str


@dataclass(frozen=True)
class TreeLevel:
    """One ancestor of a listed directory: its path and the subdirectory names the tree shows under it."""

    path: str
    dirs: Tuple[str, ...]


@dataclass(frozen=True)
class DirectoryListing:
    """One directory as the browse route reports it: its subdirectories and image files, by name.

    All paths are relative to the selected configured root. ``ancestors``
    stops at that root; it is empty when listing the root itself.
    """

    path: str
    parent: Optional[str]
    dirs: Tuple[str, ...]
    files: Tuple[str, ...]
    ancestors: Tuple[TreeLevel, ...] = ()


@dataclass(frozen=True)
class BrowseRequest:
    """A browse request: the directory to list and whether the tree's ancestor chain is wanted."""

    path: str
    with_tree: bool


@dataclass(frozen=True)
class CropBox:
    """A crop of **Load Image (Browse)**, in pixels of the upright (EXIF-transposed) image."""

    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class ViewRequest:
    """A validated view request: the image file to serve, the thumbnail bound and the crop, if any."""

    path: str
    max_size: Optional[int]
    crop: Optional[CropBox] = None


@dataclass(frozen=True)
class ResizePlan:
    """How **Resize Image** runs once: the source box it keeps, the size it scales to, and the canvas it lands on.

    ``crop`` is ``left, top, width, height`` in source pixels, ``None`` for the
    whole image; ``scaled`` and ``canvas`` are ``(width, height)``, equal unless the
    pad mode leaves room; ``offset`` is where the scaled image sits on the canvas.
    """

    crop: Optional[Tuple[int, int, int, int]]
    scaled: Tuple[int, int]
    canvas: Tuple[int, int]
    offset: Tuple[int, int]


def join_path(segments: Sequence[str]) -> str:
    """Join path segments with ``/``, skipping blanks and stray separators.

    ComfyUI's ``filename_prefix`` inputs use ``/`` for subfolders on every
    platform, so the separator is fixed. Each segment is trimmed of
    surrounding whitespace and slashes, so ``"videos/"`` and ``"/h3_clip"``
    join as ``"videos/h3_clip"``; a segment may itself contain ``/``.

    Args:
        segments: The path pieces in order; blank ones are ignored.

    Returns:
        The joined path, or ``""`` when every segment is blank.
    """
    parts: List[str] = []
    for segment in segments:
        part = segment.strip(_SEGMENT_TRIM)
        if part:
            parts.append(part)
    return PATH_SEPARATOR.join(parts)


def tail_start(batch_size: int, count: int) -> int:
    """Index where the last ``count`` items of a batch begin.

    Args:
        batch_size: Number of items in the batch.
        count: How many trailing items to keep.

    Returns:
        ``batch_size - count``, floored at 0 so a ``count`` past the batch keeps everything.
    """
    return max(0, batch_size - count)


def relative_path(value: Any, allow_empty: bool = False) -> str:
    """Validate an untrusted path before normalization, using portable separators.

    Absolute and legacy home paths require reselection under a configured root.
    Windows drives, device names, alternate streams and ambiguous trailing dots
    are refused on every platform, including when a workflow crosses platforms.
    """
    if not isinstance(value, str):
        raise TypeError("path must be a string")
    value = value.strip()
    if not value and not allow_empty:
        raise ValueError("path must not be blank")
    path = value.replace("\\", "/")
    parts = path.split("/")
    if (
        "\x00" in path
        or path.startswith(("/", "~"))
        or ntpath.splitdrive(path)[0]
        or ":" in path
        or ".." in parts
        or any(
            part not in ("", ".") and (part.endswith((".", " ")) or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part))
            for part in parts
        )
    ):
        raise ValueError("path must be relative to a configured root, without '..'; reselect legacy absolute paths with Browse")
    normalized = posixpath.normpath(path)
    if normalized == ".":
        if not allow_empty:
            raise ValueError("path must name a file")
        return ""
    return normalized


def contained_path(base_dir: str, value: Any, allow_empty: bool = False) -> str:
    """Resolve a relative path beneath a fixed base, including all symlink targets."""
    relative = relative_path(value, allow_empty)
    base = os.path.realpath(base_dir)
    target = os.path.realpath(os.path.join(base, relative))
    try:
        inside = os.path.dirname(base) != base and os.path.commonpath((base, target)) == base
    except ValueError:
        inside = False
    if not inside:
        raise ValueError("path must stay inside its configured directory")
    return target


def validate_save_path(path: Any) -> str:
    """Validate a filename prefix under ComfyUI's output directory."""
    return relative_path(path)


def expand_save_prefix(path: str, width: int, height: int, now: datetime) -> str:
    """Expand stock Save Image placeholders before checking or creating directories."""
    values = {"width": str(width), "height": str(height), "year": str(now.year)}
    values.update({name: f"{getattr(now, name):02}" for name in ("month", "day", "hour", "minute", "second")})
    for key, value in values.items():
        path = path.replace(f"%{key}%", value)
    return validate_save_path(path)


def _preview_ref(entry: Any) -> PreviewRef:
    if not isinstance(entry, dict):
        raise TypeError("each image must be an object with filename, subfolder and type")
    values: Dict[str, str] = {}
    for key in _PREVIEW_KEYS:
        value = entry.get(key)
        if not isinstance(value, str):
            raise TypeError(f"image {key} must be a string")
        values[key] = value
    if values["type"] != PREVIEW_FOLDER_TYPE:
        raise ValueError(f"only {PREVIEW_FOLDER_TYPE} previews can be saved, not {values['type']!r}")
    return PreviewRef(**values)


def parse_save_request(payload: Any) -> SaveRequest:
    """Validate the JSON body the save button posts.

    Unknown keys on an image entry are ignored: ComfyUI adds an ``id`` field
    when assets are enabled.

    Args:
        payload: The decoded JSON body, expected to be
            ``{"images": [{filename, subfolder, type}, ...], "path": str, "upscale_model": str}``.

    Returns:
        The validated request; ``upscale_model`` defaults to ``NO_UPSCALE``.

    Raises:
        TypeError: With a user-readable message when the body or an image entry has the wrong shape.
        ValueError: With a user-readable message when a field is missing or malformed.
    """
    if not isinstance(payload, dict):
        raise TypeError("request body must be a JSON object")
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        raise ValueError("no preview to save: run the workflow first")
    if len(images) > 256:
        raise ValueError("save at most 256 previews per request")
    upscale_model = payload.get("upscale_model", NO_UPSCALE)
    if not isinstance(upscale_model, str) or not upscale_model:
        raise ValueError("upscale_model must be a model name or 'none'")
    return SaveRequest(
        previews=tuple(_preview_ref(entry) for entry in images),
        path=validate_save_path(payload.get("path")),
        upscale_model=upscale_model,
    )


def preview_file_path(base_dir: str, ref: PreviewRef) -> str:
    """Resolve a temp preview, refusing traversal and file or directory symlink escapes."""
    filename = relative_path(ref.filename)
    if "/" in ref.filename or "\\" in ref.filename:
        raise ValueError("preview filename must be a basename")
    folder = relative_path(ref.subfolder, allow_empty=True)
    return contained_path(base_dir, posixpath.join(folder, filename))


def is_image_file(name: str) -> bool:
    """Whether ComfyUI's image loaders would list ``name``.

    Uses the interpreter's MIME table, excluding active SVG content. Decoders
    still validate file contents before pixels are loaded or served.

    Args:
        name: A file name or path; only the extension matters.

    Returns:
        ``True`` for an image type, ``False`` for anything else or no known type.
    """
    mime_type, _ = mimetypes.guess_type(name, strict=False)
    return mime_type is not None and mime_type.split("/")[0] == IMAGE_CONTENT_TYPE and mime_type != "image/svg+xml"


def resolve_image_path(value: Any, input_dir: str) -> str:
    """Resolve an image path relative to its selected, server-configured directory."""
    return contained_path(input_dir, value)


def parse_crop(value: Any) -> Optional[CropBox]:
    """Turn the ``crop`` widget of **Load Image (Browse)** into a box, or ``None`` for the whole image.

    The format is ``left,top,width,height`` in pixels of the upright image;
    blank means no crop. Whether the box fits the image is not checked here,
    see ``crop_box``.

    Args:
        value: The widget value, or a ``crop`` query parameter.

    Returns:
        The box, or ``None`` when the value is ``None`` or blank.

    Raises:
        TypeError: If the value is not a string.
        ValueError: If it is not four integers, or the box has no area or a negative origin.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(CROP_FORMAT_ERROR)
    if not value.strip():
        return None
    fields = value.split(CROP_SEPARATOR)
    if len(fields) != 4:
        raise ValueError(CROP_FORMAT_ERROR)
    try:
        left, top, width, height = (int(field.strip()) for field in fields)
    except ValueError:
        raise ValueError(CROP_FORMAT_ERROR) from None
    if left < 0 or top < 0 or width < 1 or height < 1:
        raise ValueError(CROP_FORMAT_ERROR)
    return CropBox(left, top, width, height)


def crop_box(crop: CropBox, size: Tuple[int, int]) -> Optional[Tuple[int, int, int, int]]:
    """The Pillow box ``(left, upper, right, lower)`` of ``crop`` on an image of ``size``.

    A box reaching past the image is cut to it, so a crop chosen on one file
    still applies to a smaller replacement. A box covering the whole image is
    no crop at all.

    Args:
        crop: The parsed crop.
        size: The image's ``(width, height)`` after the EXIF transpose.

    Returns:
        The box to crop to, or ``None`` when it would cover the whole image.

    Raises:
        ValueError: If the box lies wholly outside the image.
    """
    width, height = size
    if crop.left >= width or crop.top >= height:
        raise ValueError(f"crop {crop.left},{crop.top},{crop.width},{crop.height} lies outside the {width}x{height} image")
    box = (crop.left, crop.top, min(width, crop.left + crop.width), min(height, crop.top + crop.height))
    return None if box == (0, 0, width, height) else box


def _scan(path: str, base_dir: str) -> Tuple[List[str], List[str]]:
    """List visible contained directories and image files, ignoring escaping links."""
    dirs: List[str] = []
    files: List[str] = []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                target = contained_path(base_dir, os.path.relpath(entry.path, base_dir))
                if os.path.isdir(target):
                    dirs.append(entry.name)
                elif os.path.isfile(target) and is_image_file(entry.name):
                    files.append(entry.name)
            except (OSError, ValueError):
                continue
    return sorted(dirs, key=str.casefold), sorted(files, key=str.casefold)


def browse_directory(path: str, base_dir: str, with_tree: bool = True) -> DirectoryListing:
    """List an already resolved location, stopping ancestors at its configured root.

    Every returned path is relative to the selected root; the root itself is
    the empty string and has no parent. A file lists its containing directory.
    """
    base = os.path.realpath(base_dir)
    path = contained_path(base, os.path.relpath(path, base), allow_empty=True)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    dirs, files = _scan(path, base)
    relative = os.path.relpath(path, base).replace(os.sep, "/")
    relative = "" if relative == "." else relative
    levels: List[TreeLevel] = []
    current = relative
    if with_tree:
        while current:
            parent = posixpath.dirname(current)
            siblings, _ = _scan(contained_path(base, parent, allow_empty=True), base)
            child = posixpath.basename(current)
            if child not in siblings:
                siblings.append(child)
            levels.append(TreeLevel(parent, tuple(sorted(siblings, key=str.casefold))))
            current = parent
    return DirectoryListing(relative, posixpath.dirname(relative) if relative else None, tuple(dirs), tuple(files), tuple(reversed(levels)))


def parse_browse_request(query: Mapping[str, str], input_dir: str) -> BrowseRequest:
    """Resolve a browse request under its selected root; blank means the root."""
    return BrowseRequest(contained_path(input_dir, query.get("path", ""), allow_empty=True), query.get("tree") != "0")


def parse_view_request(query: Mapping[str, str], input_dir: str) -> ViewRequest:
    """Resolve a view request and validate its optional rendering parameters."""
    path = resolve_image_path(query.get("path", ""), input_dir)
    crop = parse_crop(query.get("crop"))
    raw = query.get("max")
    if raw is None:
        return ViewRequest(path, None, crop)
    try:
        size = int(raw)
    except ValueError:
        raise ValueError("max must be an integer") from None
    return ViewRequest(path, min(MAX_THUMBNAIL, max(MIN_THUMBNAIL, size)), crop)


def _snap(size: int, divisible_by: int) -> int:
    """``size`` rounded down to a multiple of ``divisible_by``, never below one multiple; ``0`` and ``1`` leave it alone."""
    if divisible_by <= 1:
        return size
    return max(divisible_by, size - size % divisible_by)


def _fit(source: Tuple[int, int], box: Tuple[int, int]) -> Tuple[int, int]:
    """The largest size of ``source``'s aspect that fits inside ``box``, rounded, at least one pixel each way."""
    ratio = min(box[0] / source[0], box[1] / source[1])
    return max(1, round(source[0] * ratio)), max(1, round(source[1] * ratio))


def _anchor(space: int, extent: int, position: str, start: str, end: str) -> int:
    """Where an ``extent`` sits inside ``space`` along one axis: at ``start``, at ``end``, or centred for any other position."""
    if position == start:
        return 0
    if position == end:
        return space - extent
    return (space - extent) // 2


def _target(source: Tuple[int, int], width: int, height: int, mode: str) -> Tuple[int, int]:
    """The requested size with zeros resolved: from the source in ``stretch`` and ``crop``, by aspect ratio otherwise."""
    source_width, source_height = source
    if mode in ("stretch", "crop") or (width == 0 and height == 0):
        return width or source_width, height or source_height
    if width == 0:
        return max(1, round(source_width * height / source_height)), height
    if height == 0:
        return width, max(1, round(source_height * width / source_width))
    return width, height


def _cover_crop(source: Tuple[int, int], canvas: Tuple[int, int], position: str) -> Optional[Tuple[int, int, int, int]]:
    """The largest source box with the canvas's aspect, anchored at ``position``; ``None`` when that is the whole image."""
    source_width, source_height = source
    if source_width / source_height > canvas[0] / canvas[1]:
        crop_width, crop_height = round(source_height * canvas[0] / canvas[1]), source_height
    else:
        crop_width, crop_height = source_width, round(source_width * canvas[1] / canvas[0])
    crop_width, crop_height = min(source_width, max(1, crop_width)), min(source_height, max(1, crop_height))
    if (crop_width, crop_height) == source:
        return None
    left = _anchor(source_width, crop_width, position, "left", "right")
    top = _anchor(source_height, crop_height, position, "top", "bottom")
    return left, top, crop_width, crop_height


def resize_plan(source: Tuple[int, int], width: int, height: int, mode: str, crop_position: str, divisible_by: int) -> ResizePlan:
    """Work out the geometry of one **Resize Image** run, without touching pixels.

    A zero ``width`` or ``height`` means "from the source": the source dimension
    in ``stretch`` and ``crop``, the one keeping the aspect ratio in ``resize``
    and ``pad``, and both zero the source size. ``divisible_by`` above 1 rounds
    the output size down to its multiples (never below one multiple); in ``pad``
    the canvas is snapped first and the image fitted inside it, so the output is
    always exactly the canvas. ``crop_position`` anchors the kept region in
    ``crop`` and the image on the canvas in ``pad`` (``top`` puts the padding at
    the bottom); the other axis is centred.

    Args:
        source: The image's ``(width, height)``.
        width: The requested width, ``0`` for "from the source".
        height: The requested height, likewise.
        mode: One of ``RESIZE_MODES``.
        crop_position: One of ``CROP_POSITIONS``.
        divisible_by: The pixel grid; ``0`` and ``1`` mean none.

    Returns:
        The plan: what to cut, how large to scale, the canvas, and where the image sits on it.

    Raises:
        ValueError: For an unknown mode or position.
    """
    if mode not in RESIZE_MODES:
        raise ValueError(f"unknown mode {mode!r}")
    if crop_position not in CROP_POSITIONS:
        raise ValueError(f"unknown crop_position {crop_position!r}")
    target = _target(source, width, height, mode)
    if mode == "resize":
        fitted = _fit(source, target)
        scaled = (_snap(fitted[0], divisible_by), _snap(fitted[1], divisible_by))
        return ResizePlan(None, scaled, scaled, (0, 0))
    canvas = (_snap(target[0], divisible_by), _snap(target[1], divisible_by))
    if mode == "stretch":
        return ResizePlan(None, canvas, canvas, (0, 0))
    if mode == "crop":
        return ResizePlan(_cover_crop(source, canvas, crop_position), canvas, canvas, (0, 0))
    scaled = _fit(source, canvas)
    offset = (_anchor(canvas[0], scaled[0], crop_position, "left", "right"), _anchor(canvas[1], scaled[1], crop_position, "top", "bottom"))
    return ResizePlan(None, scaled, canvas, offset)


def parse_pad_color(value: Any) -> Optional[Tuple[float, float, float]]:
    """Turn the ``pad_color`` widget of **Resize Image** into RGB in ``[0, 1]``, or ``None`` for a colour name.

    Accepted: ``r, g, b`` in 0-255, or in 0.0-1.0 when any part carries a
    decimal point (so ``1, 1, 1`` is near-black and ``1.0, 1.0, 1.0`` white);
    ``#rgb``, ``#rrggbb`` or ``#rrggbbaa`` (alpha ignored); one grey value in
    either range. Out-of-range channels are clamped. A word (``white``) is a
    colour name, which Pillow resolves on the ComfyUI side.

    Args:
        value: The widget value.

    Returns:
        The colour, or ``None`` when ``value`` is a colour name.

    Raises:
        TypeError: If the value is not a string.
        ValueError: If it is blank or in none of the forms above.
    """
    if not isinstance(value, str):
        raise TypeError(PAD_COLOR_FORMAT_ERROR)
    text = value.strip()
    if not text:
        raise ValueError(PAD_COLOR_FORMAT_ERROR)
    hexadecimal = _HEX_COLOR.match(text)
    if hexadecimal:
        digits = hexadecimal.group(1)
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        red, green, blue = (int(digits[index : index + 2], 16) / 255.0 for index in (0, 2, 4))
        return red, green, blue
    if _COLOR_NAME.match(text):
        return None
    parts = [part.strip() for part in text.split(",")]
    if len(parts) not in (1, 3):
        raise ValueError(PAD_COLOR_FORMAT_ERROR)
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise ValueError(PAD_COLOR_FORMAT_ERROR) from None
    if not all(math.isfinite(number) for number in numbers):
        raise ValueError(PAD_COLOR_FORMAT_ERROR)
    scale = 1.0 if any("." in part for part in parts) else 255.0
    channels = [min(1.0, max(0.0, number / scale)) for number in numbers]
    if len(channels) == 1:
        channels *= 3
    return channels[0], channels[1], channels[2]
