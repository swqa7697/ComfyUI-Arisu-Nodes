"""Filesystem ownership for video segments: exclusive counters, temporary destinations and ordered publication."""

from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import shutil
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .core import contained_path
from .media import revision_for
from .video import (
    COMPANION,
    RECORD_LIMIT,
    SEQUENCE_LIMIT,
    TAKE_AUDIO,
    TAKE_RECORD,
    VIDEO_SUFFIXES,
    PcmSource,
    director_take_id,
    read_sequence_record,
    read_take_record,
)

logger = logging.getLogger(__name__)
SEQUENCE_RECORD = "sequence.json"
MAX_TAKES = 512
_TEMP_PREFIX = ".arisu-tmp-"
_STALE_SECONDS = 24 * 3600
_READING: Dict[str, int] = {}
_DEFERRED: Dict[str, Callable[[], None]] = {}
_READING_LOCK = threading.Lock()

_ATTEMPTS = 100000
_PARTS = ("video.part", "audio.wav.part", "metadata.part", TAKE_RECORD + ".part")


@dataclass
class Reservation:
    """One take's exclusive counter, held by its companion directory until publication or cleanup."""

    directory: str
    stem: str
    counter: int
    published: Optional[str] = None

    @property
    def name(self) -> str:
        return f"{self.stem}_{self.counter:05}_"

    @property
    def companion(self) -> str:
        return os.path.join(self.directory, self.name + COMPANION)

    @property
    def video(self) -> str:
        return os.path.join(self.directory, self.name + ".mp4")

    def part(self, name: str) -> str:
        """A temporary file inside the reservation."""
        return os.path.join(self.companion, name)


def _next_counter(directory: str, stem: str) -> int:
    pattern = re.compile(rf"{re.escape(stem)}_(\d+)_\.(?:{'|'.join(VIDEO_SUFFIXES)}|{COMPANION[1:]})")
    used = [int(match.group(1)) for match in map(pattern.fullmatch, os.listdir(directory)) if match]
    return max(used, default=0) + 1


def _claim(directory: str, stem: str, counter: int) -> Reservation:
    for candidate in range(counter, counter + _ATTEMPTS):
        reservation = Reservation(directory, stem, candidate)
        try:
            os.mkdir(reservation.companion)
        except FileExistsError:
            continue
        # A video or symlink already at this number is a collision, never something to overwrite or follow.
        if not os.path.lexists(reservation.video):
            return reservation
        os.rmdir(reservation.companion)
    raise OSError("no free take counter")


def reserve_take(output_root: str, directory: str, stem: str) -> Reservation:
    """Create the take directory inside output and claim the next counter with an exclusive ``mkdir``.

    Containment is checked before the directory is created and again afterwards. The claim is safe across
    threads and processes; siblings such as ``clip_00001.safetensors`` do not take a number.
    """
    if not stem or stem in (".", ".."):
        raise ValueError("video prefix must end in a filename")
    target = contained_path(output_root, directory, allow_empty=True)
    os.makedirs(target, exist_ok=True)
    target = contained_path(output_root, directory, allow_empty=True)
    return _claim(target, stem, _next_counter(target, stem))


def _publish_video(reservation: Reservation):
    source = reservation.part("video.part")
    while True:
        try:
            # A hard link publishes atomically and fails when the name exists, including as a symlink.
            os.link(source, reservation.video)
        except FileExistsError:
            moved = _claim(reservation.directory, reservation.stem, reservation.counter + 1)
            for name in os.listdir(reservation.companion):
                os.replace(reservation.part(name), moved.part(name))
            os.rmdir(reservation.companion)
            reservation.counter, source = moved.counter, moved.part("video.part")
            continue
        except OSError:
            # Filesystems without hard links: claim the name exclusively, then move over our own placeholder.
            os.close(os.open(reservation.video, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            reservation.published = reservation.video
            os.replace(source, reservation.video)
            return
        reservation.published = reservation.video
        os.unlink(source)
        return


def publish_take(reservation: Reservation, has_audio: bool, build: Callable[[str, Optional[str]], Dict[str, Any]]) -> Dict[str, Any]:
    """Publish the video, then the PCM companion, then ``take.json`` last; the record makes the take visible."""
    _publish_video(reservation)
    audio = None
    if has_audio:
        audio = reservation.part(TAKE_AUDIO)
        os.replace(reservation.part("audio.wav.part"), audio)
    record = build(reservation.video, audio)
    pending = reservation.part(TAKE_RECORD + ".part")
    with open(pending, "x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(pending, reservation.part(TAKE_RECORD))
    for name in ("metadata.part",):
        if os.path.lexists(reservation.part(name)):
            os.unlink(reservation.part(name))
    return record


def discard_take(reservation: Reservation):
    """Remove one unfinished take: only this job's files, and the companion directory only when it is then empty."""
    for path in (reservation.published, *(reservation.part(name) for name in (*_PARTS, TAKE_AUDIO, TAKE_RECORD))):
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    try:
        os.rmdir(reservation.companion)
    except OSError:
        pass


def _regular(path: str) -> Optional[os.stat_result]:
    """The status of a regular file that is not a symlink, or ``None``."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def take_companion(output_root: str, path: str, revision: str) -> Tuple[Optional[Dict[str, Any]], Optional[PcmSource], bool]:
    """Find the record published beside a video and its verified PCM companion.

    Returns ``(record, pcm, pcm_lost)``. A record is used only when it names this file at this revision;
    ``pcm_lost`` reports registered PCM that is missing or was replaced.
    """
    stem, _ = posixpath.splitext(path)
    try:
        location = contained_path(output_root, posixpath.join(stem + COMPANION, TAKE_RECORD))
        info = _regular(location)
        if info is None or info.st_size > RECORD_LIMIT:
            return None, None, False
        with open(location, encoding="utf-8") as handle:
            record = read_take_record(handle.read())
    except (OSError, TypeError, ValueError):
        return None, None, False
    if record["video"]["path"] != path or record["video"]["revision"] != revision:
        return None, None, False
    audio = record["audio"]
    registered = audio.get("pcm") if audio else None
    if registered is None:
        return record, None, False
    try:
        companion = contained_path(output_root, registered["path"])
    except ValueError:
        return record, None, True
    found = _regular(companion)
    if found is None or revision_for(found) != registered["revision"] or found.st_size < audio["samples"] * audio["channels"] * 4:
        return record, None, True
    return record, PcmSource(companion, audio["rate"], audio["channels"], audio["samples"], registered["revision"]), False


def list_takes(output_root: str, project: str, legacy: bool) -> List[str]:
    """Relative paths of the videos a project offers: published takes, and Director renders in either layout."""
    found: List[str] = []

    def videos(directory: str, recorded: bool):
        try:
            absolute = contained_path(output_root, directory)
            names = sorted(os.listdir(absolute))
        except (OSError, ValueError):
            return
        for name in names:
            stem, extension = posixpath.splitext(name)
            if extension[1:] not in VIDEO_SUFFIXES or _regular(os.path.join(absolute, name)) is None:
                continue
            if recorded and _regular(os.path.join(absolute, stem + COMPANION, TAKE_RECORD)) is None:
                continue
            found.append(posixpath.join(directory, name))

    def renders(parent: str):
        try:
            names = sorted(os.listdir(contained_path(output_root, parent)))
        except (OSError, ValueError):
            return
        for name in names:
            if director_take_id(posixpath.join(parent, name)):
                videos(posixpath.join(parent, name), False)

    videos(posixpath.join(project, "videos"), True)
    renders(posixpath.join(project, "director"))
    if legacy:
        renders("arisu_director")
    return found[:MAX_TAKES]


@contextmanager
def reading(paths: List[str]) -> Iterator[None]:
    """Mark files as in use by an export; a deletion requested meanwhile runs when the last reader leaves."""
    with _READING_LOCK:
        for path in paths:
            _READING[path] = _READING.get(path, 0) + 1
    try:
        yield
    finally:
        pending: List[Callable[[], None]] = []
        with _READING_LOCK:
            for path in paths:
                _READING[path] -= 1
                if not _READING[path]:
                    del _READING[path]
                    if path in _DEFERRED:
                        pending.append(_DEFERRED.pop(path))
        for action in pending:
            action()


def deletion_plan(output_root: str, path: str, revision: str) -> List[Tuple[str, int]]:
    """The files of one ordinary Arisu take that may be removed, as ``(absolute path, bytes)``.

    Ownership is proven on the server: the video sits outside Director and export directories, and a published
    record beside it names this file at the requested revision. Anything else raises ``PermissionError``.
    """
    directory = posixpath.dirname(path)
    parts = directory.split("/")
    video = contained_path(output_root, path)
    info = _regular(video)
    if info is None:
        raise FileNotFoundError("take not found")
    if director_take_id(directory) or "exports" in parts or "director" in parts or parts[0] == "arisu_director":
        raise PermissionError("only ordinary takes can be deleted here")
    if revision_for(info) != revision:
        raise PermissionError("the take changed; describe it again")
    record, _, _ = take_companion(output_root, path, revision)
    if record is None or record.get("origin") != "ordinary":
        raise PermissionError("only ordinary takes can be deleted here")
    stem, _ = posixpath.splitext(path)
    companion = contained_path(output_root, stem + COMPANION)
    files = [(os.path.join(companion, TAKE_RECORD), _regular(os.path.join(companion, TAKE_RECORD)))]
    registered = ((record.get("audio") or {}).get("pcm") or {}).get("path")
    # Only the companion this record registers belongs to the take; anything else in the directory is the user's.
    if registered == posixpath.join(stem + COMPANION, TAKE_AUDIO):
        files.append((os.path.join(companion, TAKE_AUDIO), _regular(os.path.join(companion, TAKE_AUDIO))))
    files.append((video, info))
    return [(name, found.st_size) for name, found in files if found is not None]


def delete_take(output_root: str, path: str, revision: str) -> str:
    """Delete a verified take now, or defer it while an export reads the video.

    Returns ``deleted``, ``deferred``, or ``refused`` when a file could not be removed; a failure is never
    reported as success.
    """
    files = deletion_plan(output_root, path, revision)
    video = files[-1][0]

    def remove() -> bool:
        try:
            # Re-verify at the moment of deletion. The video goes first: if it cannot be removed, the take stays
            # published and whole instead of becoming an unlisted orphan.
            for name, _ in reversed(deletion_plan(output_root, path, revision)):
                os.unlink(name)
        except OSError:
            logger.warning("take deletion failed", exc_info=True)
            return False
        try:
            os.rmdir(os.path.dirname(files[0][0]))
        except OSError:
            # The companion directory holds files this take does not own; they stay.
            pass
        return True

    with _READING_LOCK:
        if video in _READING:
            _DEFERRED[video] = remove
            return "deferred"
    return "deleted" if remove() else "refused"


def _export_counters(exports: str, name: str) -> List[int]:
    pattern = re.compile(rf"{re.escape(name)}_(\d{{5,}})")
    try:
        return sorted(int(match.group(1)) for match in map(pattern.fullmatch, os.listdir(exports)) if match)
    except FileNotFoundError:
        return []


def predicted_export(output_root: str, project: str, name: str) -> str:
    """The relative film path the next export would get, for preflight."""
    exports = contained_path(output_root, posixpath.join(project, "exports"))
    label = f"{name}_{max(_export_counters(exports, name), default=0) + 1:05}"
    return posixpath.join(project, "exports", label, label + ".mp4")


def find_export(output_root: str, project: str, name: str, job: str) -> Optional[Dict[str, Any]]:
    """The published export of this job, when its film is still the recorded file."""
    exports = contained_path(output_root, posixpath.join(project, "exports"))
    for counter in reversed(_export_counters(exports, name)):
        location = os.path.join(exports, f"{name}_{counter:05}", SEQUENCE_RECORD)
        found = _regular(location)
        # The size is bounded before the file is read, not after.
        if found is None or found.st_size > SEQUENCE_LIMIT:
            continue
        try:
            with open(location, encoding="utf-8") as handle:
                record = read_sequence_record(handle.read())
            film = _regular(contained_path(output_root, record["film"]["path"]))
        except (OSError, ValueError):
            continue
        if record["job"] == job and film is not None and revision_for(film) == record["film"]["revision"]:
            return record
    return None


def export_workspace(output_root: str, project: str, job: str) -> str:
    """Create this job's private directory under ``<project>/exports`` and sweep abandoned ones."""
    relative = posixpath.join(project, "exports")
    exports = contained_path(output_root, relative)
    os.makedirs(exports, exist_ok=True)
    exports = contained_path(output_root, relative)
    for name in os.listdir(exports):
        stale = os.path.join(exports, name)
        try:
            if name.startswith(_TEMP_PREFIX) and time.time() - os.lstat(stale).st_mtime > _STALE_SECONDS:
                shutil.rmtree(stale, ignore_errors=True)
        except OSError:
            continue
    workspace = os.path.join(exports, _TEMP_PREFIX + job)
    # An existing directory means this job is already running; a second run must not share its files.
    os.mkdir(workspace)
    return workspace


def publish_export(workspace: str, name: str, film: str, build: Callable[[int, str], Dict[str, Any]]) -> Dict[str, Any]:
    """Name the film and write its record inside the workspace, then expose the directory with one rename.

    The final directory appears only when both files are complete. A concurrent export that took the same
    counter makes the rename fail, and this export advances to the next one.
    """
    exports = os.path.dirname(workspace)
    counter = max(_export_counters(exports, name), default=0)
    current = film
    while True:
        counter += 1
        label = f"{name}_{counter:05}"
        final = os.path.join(exports, label)
        if os.path.lexists(final):
            continue
        named = os.path.join(workspace, label + ".mp4")
        os.replace(current, named)
        current = named
        record = build(counter, named)
        pending = os.path.join(workspace, SEQUENCE_RECORD + ".part")
        with open(pending, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=1)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(pending, os.path.join(workspace, SEQUENCE_RECORD))
        try:
            os.rename(workspace, final)
        except OSError:
            if os.path.lexists(final):
                continue
            raise
        return record


def discard_workspace(workspace: str):
    """Remove one job's unfinished export; published versions and sources are never touched."""
    if os.path.basename(workspace).startswith(_TEMP_PREFIX):
        shutil.rmtree(workspace, ignore_errors=True)
