"""Filesystem ownership for video segments: exclusive counters, temporary destinations and ordered publication."""

from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import os
import posixpath
import re
import shutil
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Set, Tuple

from .core import contained_path, relative_path
from .media import revision_for
from .paths import select_root
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
_DEFERRED: Dict[str, Tuple[Set[str], Callable[[], str]]] = {}
_MAX_DELETE_ENTRIES = 4096
_READING_LOCK = threading.Lock()
_DELETE_KEY = os.urandom(32)

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
        return f"{self.stem}_{self.counter:05}_" if self.counter else self.stem

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


def reserve_take(output_root: str, directory: str, stem: str, *, directed: bool = False) -> Reservation:
    """Create the take directory inside output and claim the next counter with an exclusive ``mkdir``.

    Containment is checked before the directory is created and again afterwards. The claim is safe across
    threads and processes; siblings such as ``clip_00001.safetensors`` do not take a number.
    """
    if not stem or stem in (".", ".."):
        raise ValueError("video prefix must end in a filename")
    target = contained_path(output_root, directory, allow_empty=True)
    if directed:
        # This saver owns both outputs. A previously claimed UUID is never reused, even after a retry.
        if not director_take_id(directory) or stem != "clip":
            raise ValueError("invalid Director destination")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        target = contained_path(output_root, directory)
        os.mkdir(target)
        reservation = Reservation(contained_path(output_root, directory), stem, 0)
        try:
            os.mkdir(reservation.companion)
        except OSError:
            os.rmdir(target)
            raise
        return reservation
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
            if not reservation.counter:
                raise
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
    for path in (reservation.published, *(reservation.part(name) for name in (*_PARTS, TAKE_AUDIO, TAKE_RECORD, "latent.safetensors"))):
        if path:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass
    try:
        os.rmdir(reservation.companion)
        if not reservation.counter:
            os.rmdir(reservation.directory)
    except OSError:
        pass


def _regular(path: str) -> Optional[os.stat_result]:
    """The status of a regular file that is not a symlink, or ``None``."""
    try:
        info = os.lstat(path)
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def take_companion(output_root: str, path: str) -> Tuple[Optional[Dict[str, Any]], Optional[PcmSource], bool]:
    """Find the record published beside a video and its verified PCM companion.

    Returns ``(record, pcm, pcm_lost)``. A record must name this video and its own soundtrack.
    ``pcm_lost`` reports registered PCM that is unavailable or too short.
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
    if record["video"]["path"] != path:
        return None, None, False
    directed = director_take_id(posixpath.dirname(path))
    record["origin"] = "director" if directed else "ordinary"
    if directed:
        record["take"] = directed
    audio = record["audio"]
    registered = audio.get("pcm") if audio else None
    if registered is None:
        return record, None, False
    if registered["path"] != posixpath.join(stem + COMPANION, TAKE_AUDIO):
        return record, None, True
    try:
        companion = contained_path(output_root, registered["path"])
    except ValueError:
        return record, None, True
    found = _regular(companion)
    if found is None or found.st_size < audio["samples"] * audio["channels"] * 4:
        return record, None, True
    return record, PcmSource(companion, audio["rate"], audio["channels"], audio["samples"]), False


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
            if (recorded or name == "clip.mp4" and director_take_id(directory)) and _regular(
                os.path.join(absolute, stem + COMPANION, TAKE_RECORD)
            ) is None:
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
        with _READING_LOCK:
            for path in paths:
                _READING[path] -= 1
                if not _READING[path]:
                    del _READING[path]
            for revision, (files, action) in list(_DEFERRED.items()):
                if files.isdisjoint(_READING):
                    del _DEFERRED[revision]
                    action()


@contextmanager
def _file_at(base: str, path: str) -> Iterator[Tuple[str, Optional[int]]]:
    """Access a literal entry under the configured root. Pin its parent where directory descriptors are supported."""
    parts = relative_path(path).split("/")
    root = os.path.realpath(base)
    directory = contained_path(root, "/".join(parts[:-1]), allow_empty=True)
    if os.path.normcase(directory) != os.path.normcase(os.path.join(root, *parts[:-1])):
        raise ValueError("symlinked deletion paths are not allowed")
    if os.open not in os.supports_dir_fd:
        yield os.path.join(directory, parts[-1]), None
        return
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent = os.open(root, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        yield parts[-1], parent
    finally:
        os.close(parent)


@dataclass(frozen=True)
class DeletionFile:
    path: str
    info: os.stat_result

    @property
    def size(self) -> int:
        return self.info.st_size

    @property
    def revision(self) -> str:
        return revision_for(self.info)

    def matches(self, current: os.stat_result, unlinked: int) -> bool:
        if self.revision == revision_for(current):
            return True
        # Unlinking a reviewed hard link earlier in this group changes its sibling's ctime and link count.
        old = self.info
        return (
            unlinked > 0
            and os.path.samestat(old, current)
            and current.st_nlink + unlinked == old.st_nlink
            and (current.st_mode, current.st_uid, current.st_gid, current.st_size, current.st_mtime_ns)
            == (old.st_mode, old.st_uid, old.st_gid, old.st_size, old.st_mtime_ns)
        )


@dataclass(frozen=True)
class DeletionPlan:
    files: List[DeletionFile]
    directories: Dict[str, os.stat_result]
    revision: str

    @property
    def directory(self) -> Optional[str]:
        """The top directory removed in full, if the selection is a take."""
        return next(iter(self.directories), None)


def _ordinary_directory(base: str, video: DeletionFile) -> Optional[str]:
    """Recognize the saver's reserved directory, or a recorded take outside the standard layout."""
    directory = posixpath.splitext(video.path)[0] + COMPANION
    parent, name = posixpath.split(video.path)
    if posixpath.basename(parent) == "videos" and re.fullmatch(r".+_[0-9]{5,}_\.mp4", name):
        with _file_at(base, directory) as (entry, fd):
            try:
                info = os.stat(entry, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                return None
            return directory if stat.S_ISDIR(info.st_mode) else None
    try:
        with _file_at(base, posixpath.join(directory, TAKE_RECORD)) as (name, parent):
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_size > RECORD_LIMIT:
                return None
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(name, flags, dir_fd=parent), "rb") as handle:
                if not os.path.samestat(os.fstat(handle.fileno()), info):
                    return None
                record = read_take_record(handle.read(RECORD_LIMIT + 1).decode("utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if record.get("origin") == "ordinary" and record["video"]["path"] == video.path:
        return directory
    return None


@contextmanager
def _scan_directory(base: str, path: str) -> Iterator[Tuple[os.stat_result, Iterator[os.DirEntry]]]:
    """Scan a pinned directory without following a directory link."""
    with _file_at(base, path) as (name, parent):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("invalid take directory")
        absolute = os.path.join(os.path.realpath(base), *path.split("/"))
        if os.path.ismount(absolute):
            raise ValueError("cannot delete a mounted take directory")
        if os.scandir not in os.supports_fd:
            with os.scandir(absolute) as entries:
                yield info, entries
            return
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            with os.scandir(descriptor) as entries:
                yield os.fstat(descriptor), entries
        finally:
            os.close(descriptor)


def _snapshot_directory(base: str, directory: str) -> Tuple[List[DeletionFile], Dict[str, os.stat_result]]:
    files = []
    directories = {}
    pending = [directory]
    while pending:
        path = pending.pop()
        with _scan_directory(base, path) as (info, entries):
            directories[path] = info
            for entry in entries:
                if len(files) + len(directories) + len(pending) >= _MAX_DELETE_ENTRIES:
                    raise ValueError("too many entries in the take directory")
                child = posixpath.join(path, entry.name)
                if relative_path(child) != child:
                    raise ValueError("unexpected filename in the take directory")
                child_info = entry.stat(follow_symlinks=False)
                if child_info.st_dev != info.st_dev:
                    raise ValueError("cannot cross a mounted filesystem during deletion")
                if (
                    stat.S_ISDIR(child_info.st_mode)
                    and not getattr(child_info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    pending.append(child)
                else:
                    # Links are included as directory entries, without visiting or reading their targets.
                    files.append(DeletionFile(child, child_info))
    return sorted(files, key=lambda item: item.path), dict(sorted(directories.items()))


def deletion_plan(roots: Mapping[str, str], root: str, path: str) -> DeletionPlan:
    """Bind confirmation to the selected video or to the inventory of its take directory."""
    base = select_root(roots, root)
    path = relative_path(path)
    mime, encoding = mimetypes.guess_type(path, strict=False)
    if encoding or not (mime or "").startswith("video/"):
        raise ValueError("select a video file")
    with _file_at(base, path) as (name, parent):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("select a regular video file")
        video = DeletionFile(path, info)
    directory = None
    directed = root == "output" and director_take_id(posixpath.dirname(path))
    if directed:
        directory = posixpath.dirname(path)
    elif root == "output":
        directory = _ordinary_directory(base, video)
    files, directories = _snapshot_directory(base, directory) if directory else ([], {})
    if directed:
        if not any(item.path == path and item.revision == video.revision for item in files):
            raise ValueError("the selected video changed during listing")
    else:
        files.append(video)
    identities = [(item.path, item.revision) for item in files]
    folders = [(name, revision_for(info)) for name, info in directories.items()]
    payload = json.dumps([root, os.path.realpath(base), identities, folders]).encode("utf-8")
    return DeletionPlan(files, directories, hmac.digest(_DELETE_KEY, payload, "sha256").hex())


def delete_video(roots: Mapping[str, str], root: str, path: str, revision: str, removed: Optional[List[str]] = None) -> str:
    """Remove the confirmed inventory, revalidating it after every active reader has finished."""
    base = select_root(roots, root)

    def remove() -> str:
        changed = False
        try:
            plan = deletion_plan(roots, root, path)
            if plan.revision != revision:
                return "refused"
            files = {os.path.join(os.path.realpath(base), *item.path.split("/")) for item in plan.files}
            if not files.isdisjoint(_READING):
                _DEFERRED[revision] = (files, remove)
                return "deferred"
            unlinked: Dict[Tuple[int, int], int] = {}
            # Start with the requested video. A write-protected video thus keeps its complete take.
            for item in sorted(plan.files, key=lambda item: item.path != path):
                with _file_at(base, item.path) as (name, parent):
                    inode = (item.info.st_dev, item.info.st_ino)
                    if not item.matches(os.stat(name, dir_fd=parent, follow_symlinks=False), unlinked.get(inode, 0)):
                        raise PermissionError("a confirmed file changed before removal")
                    os.unlink(name, dir_fd=parent)
                    changed = True
                    if item.info.st_nlink > 1:
                        unlinked[inode] = unlinked.get(inode, 0) + 1
                    if removed is not None:
                        removed.append(item.path)
            # A new unlisted entry prevents rmdir. An empty directory is removed only if it is the reviewed inode.
            for folder, info in reversed(plan.directories.items()):
                with _file_at(base, folder) as (name, parent):
                    if not os.path.samestat(info, os.stat(name, dir_fd=parent, follow_symlinks=False)):
                        raise PermissionError("a confirmed directory changed before removal")
                    os.rmdir(name, dir_fd=parent)
        except (OSError, ValueError):
            if changed:
                logger.warning("video deletion was incomplete", exc_info=True)
                return "partial"
            logger.info("video deletion refused", exc_info=True)
            return "refused"
        return "deleted"

    with _READING_LOCK:
        return remove()


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
    """The published export of this job, when the recorded film exists in that version."""
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
            label = f"{name}_{counter:05}"
            path = posixpath.join(project, "exports", label, label + ".mp4")
            if record["job"] != job or record["film"]["path"] != path:
                continue
            film = _regular(contained_path(output_root, path))
        except (OSError, ValueError):
            continue
        if film is not None and film.st_size:
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
