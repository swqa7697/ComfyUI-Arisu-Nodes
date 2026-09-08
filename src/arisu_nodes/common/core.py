"""ComfyUI-free logic for the common node family.

Everything here imports only the standard library so it can be unit-tested in
the project's own environment, without torch or ComfyUI on the path.
"""

from __future__ import annotations

import string
from typing import List, Sequence

MAX_PATH_SEGMENTS = 16
PATH_SEPARATOR = "/"
_SEGMENT_TRIM = string.whitespace + PATH_SEPARATOR


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
