"""ComfyUI-free logic for the common node family.

Everything here imports only the standard library so it can be unit-tested in
the project's own environment, without torch or ComfyUI on the path.
"""

from __future__ import annotations

import os.path
import posixpath
import string
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

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


def validate_save_path(path: Any) -> str:
    """Check a save path is a filename prefix inside ComfyUI's output directory.

    The prefix follows Save Image's ``filename_prefix`` rules (subfolders via
    ``/``, a counter suffix added on save, ``%width%``-style placeholders). A
    blank prefix would save as ``._00001_.png`` and an absolute or ``..`` path
    would leave the output directory, so those are refused here, before
    ``folder_paths.get_save_image_path`` sees them.

    Args:
        path: The value of the node's ``path`` widget.

    Returns:
        The path with surrounding whitespace removed.

    Raises:
        ValueError: If the path is not a string, is blank, is absolute, or
            contains a ``..`` component.
    """
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must not be blank")
    path = path.strip()
    normalized = posixpath.normpath(path.replace("\\", "/"))
    if normalized.startswith("/") or os.path.isabs(path) or ".." in normalized.split("/"):
        raise ValueError("path must stay inside ComfyUI's output directory: no absolute paths and no '..'")
    return path


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
    upscale_model = payload.get("upscale_model", NO_UPSCALE)
    if not isinstance(upscale_model, str) or not upscale_model:
        raise ValueError("upscale_model must be a model name or 'none'")
    return SaveRequest(
        previews=tuple(_preview_ref(entry) for entry in images),
        path=validate_save_path(payload.get("path")),
        upscale_model=upscale_model,
    )


def preview_file_path(base_dir: str, ref: PreviewRef) -> str:
    """Resolve a preview reference to a file under ``base_dir``, refusing to escape it.

    Mirrors the checks of ComfyUI's ``/view`` endpoint: the filename may not be
    absolute or contain ``..``, only its basename is used, and the subfolder
    must resolve to a directory inside ``base_dir``.

    Args:
        base_dir: The absolute directory the folder type maps to (the temp directory).
        ref: The preview as reported to the frontend.

    Returns:
        The absolute path of the preview file. Whether it exists is not checked here.

    Raises:
        ValueError: If the filename or subfolder would leave ``base_dir``.
    """
    if not ref.filename or ref.filename[0] == "/" or ".." in ref.filename:
        raise ValueError(f"invalid preview filename {ref.filename!r}")
    base_dir = os.path.abspath(base_dir)
    folder = os.path.abspath(os.path.join(base_dir, ref.subfolder))
    if os.path.commonpath((folder, base_dir)) != base_dir:
        raise ValueError(f"invalid preview subfolder {ref.subfolder!r}")
    return os.path.join(folder, os.path.basename(ref.filename))
