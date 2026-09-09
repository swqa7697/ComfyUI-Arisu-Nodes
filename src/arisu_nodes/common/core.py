"""ComfyUI-free logic for the common node family.

Everything here imports only the standard library so it can be unit-tested in
the project's own environment, without torch or ComfyUI on the path.
"""

from __future__ import annotations

import mimetypes
import os
import os.path
import posixpath
import re
import string
from dataclasses import dataclass
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
# The dialog's tree: the label of the home root, and what ``/proc/self/mounts``
# entries are left out of the mounted-disk roots: kernel and desktop pseudo
# filesystems (autofs placeholders too, since listing one triggers the mount),
# and the mount prefixes nobody keeps images under, with the desktop's
# removable-media directory carved back out. ``/home`` stays out because the
# user's own home is already a root and other users are hidden.
HOME_LABEL = "Home"
PSEUDO_FILESYSTEMS = frozenset(
    {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "squashfs", "overlay", "autofs", "nsfs", "fuse.portal"}
)
EXCLUDED_MOUNT_PREFIXES = ("/boot", "/dev", "/efi", "/home", "/proc", "/run", "/snap", "/sys", "/tmp", "/usr", "/var")
USER_MEDIA_PREFIX = "/run/media"
_MOUNT_ESCAPE = re.compile(r"\\([0-7]{3})")


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
class TreeRoot:
    """One top-level entry of the browse dialog's tree: its label and the directory it opens."""

    label: str
    path: str


@dataclass(frozen=True)
class TreeLevel:
    """One ancestor of a listed directory: its path and the subdirectory names the tree shows under it."""

    path: str
    dirs: Tuple[str, ...]


@dataclass(frozen=True)
class DirectoryListing:
    """One directory as the browse route reports it: its subdirectories and image files, by name.

    ``ancestors`` is the chain from the tree root containing the directory (or
    the filesystem root when none does) down to its parent, each with the
    subdirectories the tree shows there; empty when the directory is a root.
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
class ViewRequest:
    """A validated view request: the image file to serve and the thumbnail bound, if any."""

    path: str
    max_size: Optional[int]


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


def is_image_file(name: str) -> bool:
    """Whether ComfyUI's image loaders would list ``name``.

    Mirrors ``folder_paths.filter_files_content_types(files, ["image"])`` for
    one name: the guessed MIME type's major type is ``image``. There is no
    fixed extension list; the interpreter's ``mimetypes`` table decides, as it
    does for **Load Image**.

    Args:
        name: A file name or path; only the extension matters.

    Returns:
        ``True`` for an image type, ``False`` for anything else or no known type.
    """
    mime_type, _ = mimetypes.guess_type(name, strict=False)
    return mime_type is not None and mime_type.split("/")[0] == IMAGE_CONTENT_TYPE


def resolve_image_path(value: Any, input_dir: str) -> str:
    """Turn the ``path`` widget of **Load Image (Browse)** into an absolute file path.

    Three forms are accepted: an absolute path, a ``~`` path, and a path
    relative to ComfyUI's input directory (``sub/a.png``). Whether the file
    exists is not checked here.

    Args:
        value: The widget value.
        input_dir: ComfyUI's input directory, the base for relative paths.

    Returns:
        The normalized absolute path.

    Raises:
        ValueError: If the value is not a string or is blank.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must not be blank")
    path = os.path.expanduser(value.strip())
    if not os.path.isabs(path):
        path = os.path.join(input_dir, path)
    return os.path.abspath(path)


def is_filesystem_root(path: str) -> bool:
    """Whether ``path`` is ``/`` or a drive root, the one directory that is its own parent."""
    return os.path.dirname(path) == path


def _under(path: str, prefix: str) -> bool:
    """Whether ``path`` is ``prefix`` or inside it, by whole components (``/run`` never covers ``/runtime``)."""
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _unescape_mount(field: str) -> str:
    """Decode the octal escapes ``/proc/self/mounts`` uses for space, tab, newline and backslash."""
    return _MOUNT_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), field)


def mount_points(mounts_text: str, home: str) -> Tuple[str, ...]:
    """The mount points worth a tree root, from the content of ``/proc/self/mounts``.

    Kept: every mount whose type is not a pseudo filesystem and whose point is
    not the filesystem root, not ``home`` or one of its ancestors, and not under
    ``EXCLUDED_MOUNT_PREFIXES`` (``USER_MEDIA_PREFIX`` excepted). Nothing here
    touches the mount points themselves, so an unreachable share cannot block.

    Args:
        mounts_text: The file's content, one ``device point type options ...`` line per mount.
        home: The current user's home directory.

    Returns:
        The kept mount points, deduplicated and sorted case-insensitively.
    """
    home = os.path.abspath(home)
    kept = set()
    for line in mounts_text.splitlines():
        fields = line.split()
        if len(fields) < 3 or fields[2] in PSEUDO_FILESYSTEMS:
            continue
        point = _unescape_mount(fields[1])
        if is_filesystem_root(point) or _under(home, point):
            continue
        if any(_under(point, prefix) for prefix in EXCLUDED_MOUNT_PREFIXES) and not _under(point, USER_MEDIA_PREFIX):
            continue
        kept.add(point)
    return tuple(sorted(kept, key=str.casefold))


def tree_roots(home: str, mounts_text: Optional[str], volumes: Sequence[str], drives: Sequence[str]) -> Tuple[TreeRoot, ...]:
    """Assemble the dialog's tree roots: the home directory first, then the mounted disks.

    Args:
        home: The current user's home directory.
        mounts_text: The content of ``/proc/self/mounts`` on Linux, ``None`` elsewhere.
        volumes: The mounted volumes on macOS (the entries of ``/Volumes`` other than the boot volume).
        drives: The drive roots on Windows (``C:\\`` and so on).

    Returns:
        The roots; a mount or volume is labelled by its last path component, a drive by itself.
    """
    home = os.path.abspath(home)
    roots = [TreeRoot(HOME_LABEL, home)]
    disks = list(mount_points(mounts_text, home)) if mounts_text is not None else []
    disks.extend(sorted(volumes, key=str.casefold))
    roots.extend(TreeRoot(os.path.basename(disk) or disk, disk) for disk in disks)
    roots.extend(TreeRoot(drive, drive) for drive in drives)
    return tuple(roots)


def is_restricted(path: str, roots: Sequence[str], home: str) -> bool:
    """Whether the tree hides the subdirectories of ``path``.

    Two directories are restricted: a filesystem root that is not itself a
    tree root (``/``; Windows drives are roots), and the parent of the home
    directory (``/home``, ``/Users``, ``C:\\Users``), which holds other users.

    Args:
        path: An absolute directory.
        roots: The paths of the tree roots.
        home: The current user's home directory.
    """
    return (is_filesystem_root(path) and path not in roots) or path == os.path.dirname(os.path.abspath(home))


def containing_root(path: str, roots: Sequence[str]) -> Optional[str]:
    """The deepest tree root holding ``path``, or ``None`` when no root does.

    Args:
        path: An absolute directory.
        roots: The paths of the tree roots.
    """
    best: Optional[str] = None
    for root in roots:
        try:
            inside = os.path.commonpath((root, path)) == os.path.normpath(root)
        except ValueError:  # different drives on Windows
            continue
        if inside and (best is None or len(root) > len(best)):
            best = root
    return best


def _scan(path: str) -> Tuple[List[str], List[str]]:
    """The subdirectory and image file names of ``path``, unsorted; hidden (``.``) entries are skipped."""
    dirs: List[str] = []
    files: List[str] = []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append(entry.name)
            elif entry.is_file() and is_image_file(entry.name):
                files.append(entry.name)
    return dirs, files


def _tree_level(path: str, child: str, restricted: bool) -> TreeLevel:
    """The level for ``path`` with ``child``, the next directory down the chain, always present."""
    dirs: List[str] = []
    if not restricted:
        try:
            dirs, _ = _scan(path)
        except PermissionError:
            dirs = []
    if child not in dirs:
        dirs.append(child)
    return TreeLevel(path, tuple(sorted(dirs, key=str.casefold)))


def _ancestors(path: str, roots: Sequence[str], home: str) -> Tuple[TreeLevel, ...]:
    """The levels from the root containing ``path`` (or the filesystem root) down to its parent."""
    top = containing_root(path, roots)
    levels: List[TreeLevel] = []
    current = path
    while current != top and not is_filesystem_root(current):
        parent = os.path.dirname(current)
        levels.append(_tree_level(parent, os.path.basename(current), is_restricted(parent, roots, home)))
        current = parent
    return tuple(reversed(levels))


def browse_directory(path: str, roots: Sequence[str], home: str, with_tree: bool = True) -> DirectoryListing:
    """List the subdirectories and image files of ``path`` for the browse dialog.

    A file path lists the directory holding it, so the dialog opens where the
    widget's current value lives. Hidden entries (names starting with ``.``)
    are skipped, only files passing ``is_image_file`` are reported, and both
    lists are sorted case-insensitively. A restricted directory (see
    ``is_restricted``) reports no subdirectories. With ``with_tree`` the
    ancestor chain is scanned too; every level keeps the directory on the
    chain even when it is hidden, restricted, or unreadable.

    Args:
        path: A directory, or a file inside the directory to list.
        roots: The paths of the tree roots.
        home: The current user's home directory.
        with_tree: Whether to scan the ancestor chain; a request from the tree itself already has it.

    Returns:
        The listing; ``parent`` is ``None`` at a filesystem root.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
        NotADirectoryError: If ``path`` is neither a directory nor a file.
        PermissionError: If the directory cannot be read.
    """
    path = os.path.abspath(path)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    dirs, files = _scan(path)
    if is_restricted(path, roots, home):
        dirs = []
    parent = os.path.dirname(path)
    return DirectoryListing(
        path=path,
        parent=None if parent == path else parent,
        dirs=tuple(sorted(dirs, key=str.casefold)),
        files=tuple(sorted(files, key=str.casefold)),
        ancestors=_ancestors(path, roots, home) if with_tree else (),
    )


def parse_browse_request(query: Mapping[str, str], input_dir: str) -> BrowseRequest:
    """The directory a browse request asks for; the input directory when ``path`` is missing or blank.

    Args:
        query: The request's query parameters, ``path`` and optionally ``tree`` (``0`` skips the ancestor chain).
        input_dir: ComfyUI's input directory, the dialog's starting point.

    Returns:
        The request, its path absolute and ``~`` expanded.
    """
    path = query.get("path", "").strip()
    return BrowseRequest(
        path=os.path.abspath(os.path.expanduser(path)) if path else os.path.abspath(input_dir),
        with_tree=query.get("tree") != "0",
    )


def parse_view_request(query: Mapping[str, str]) -> ViewRequest:
    """Validate a view request: an absolute image path and an optional thumbnail bound.

    Args:
        query: The request's query parameters, ``path`` and optionally ``max``.

    Returns:
        The request; ``max_size`` is clamped to ``[MIN_THUMBNAIL, MAX_THUMBNAIL]`` or ``None`` when absent.

    Raises:
        ValueError: If ``path`` is missing, relative, or not an image type, or ``max`` is not an integer.
    """
    path = query.get("path", "").strip()
    if not path or not os.path.isabs(path):
        raise ValueError("path must be an absolute file path")
    if not is_image_file(path):
        raise ValueError(f"not an image file type: {os.path.basename(path)}")
    raw = query.get("max")
    if raw is None:
        return ViewRequest(path, None)
    try:
        size = int(raw)
    except ValueError:
        raise ValueError("max must be an integer") from None
    return ViewRequest(path, min(MAX_THUMBNAIL, max(MIN_THUMBNAIL, size)))
