"""Contained media file access shared by every family: authorized opens, revisions and restricted PyAV containers."""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, BinaryIO, Iterator, Mapping, Protocol, Tuple

import av

from .core import contained_path
from .paths import select_root

FORMATS = "mov,matroska,webm,wav,mp3,flac,ogg,aac,aiff,avi,asf,mpeg,mpegts"


class UnsupportedMedia(ValueError):
    """A file is not supported as a finite, self-contained resource."""


class StaleResource(ValueError):
    """A source changed after a selection or bundle was prepared."""


class MediaLocation(Protocol):
    """A file named by an authorized root ID, a relative path and an optional expected revision."""

    root: str
    path: str
    revision: str


@dataclass(frozen=True)
class MediaRef:
    """The plain location used where no family-specific descriptor exists."""

    root: str
    path: str
    revision: str = ""


def source_path(roots: Mapping[str, str], root: str, path: str) -> str:
    """Resolve a relative regular file within the current administrator roots."""
    resolved = contained_path(select_root(roots, root), path)
    if not stat.S_ISREG(os.stat(resolved).st_mode):
        raise ValueError("resource must be a regular file")
    return resolved


def revision_for(info: os.stat_result) -> str:
    """Fingerprint ordinary source replacement without reading file contents."""
    return hashlib.sha256(str((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)).encode()).hexdigest()


@contextmanager
def source_file(roots: Mapping[str, str], item: MediaLocation) -> Iterator[BinaryIO]:
    """Open and revalidate a contained file, never a decoder-supplied destination."""
    path = source_path(roots, item.root, item.path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("resource must be a regular file")
        current = source_path(roots, item.root, item.path)
        if revision_for(os.stat(current)) != revision_for(info) or (item.revision and item.revision != revision_for(info)):
            raise StaleResource("source changed; rerun or reselect the resource")
        yield handle


def deny_secondary(*args: Any, **kwargs: Any) -> BinaryIO:
    """Refuse all decoder-initiated additional files or network connections."""
    raise UnsupportedMedia("external media references are not supported")


def open_media(handle: BinaryIO) -> av.container.InputContainer:
    """Permit only self-contained demuxers on the already-open main file."""
    return av.open(handle, mode="r", io_open=deny_secondary, options={"protocol_whitelist": "pipe", "format_whitelist": FORMATS})


def streams(container: av.container.InputContainer) -> Tuple[Any, Any]:
    """Choose the first real video and first audio stream, ignoring cover art."""
    video = next((s for s in container.streams.video if not int(s.disposition) & 0x400), None)
    audio = next(iter(container.streams.audio), None)
    return video, audio


def origin_for(stream: Any) -> Fraction:
    """Presentation origin for source-relative editor times."""
    return Fraction(stream.start_time or 0) * stream.time_base
