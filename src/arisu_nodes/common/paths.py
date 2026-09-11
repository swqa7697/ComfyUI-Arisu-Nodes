"""Server-owned image roots, initialized from protected system-user configuration.

This stdlib-only module owns configuration I/O. No workflow, HTTP request or
ComfyUI user setting can supply the configuration location or add a root.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)
CONFIG_NAME = "config.arisu.jsonc"
CONFIG_TEMPLATE = """{
  // Add existing absolute image directories, for example "photos": "/data/photos".
  // Only allow directories you intend clients of this server to access.
  // Restart ComfyUI after editing this file. Trailing commas are not supported.
  "roots": {}
}
"""
_roots: Optional[Mapping[str, str]] = None


def _without_comments(text: str) -> str:
    """Replace JSONC comments with whitespace without changing string contents."""
    chars = list(text)
    index = 0
    quoted = False
    while index < len(text):
        char = text[index]
        if quoted:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif text.startswith("//", index) or text.startswith("/*", index):
            start = index
            if text[index + 1] == "/":
                while index < len(text) and text[index] not in "\r\n":
                    index += 1
            else:
                end = text.find("*/", index + 2)
                if end < 0:
                    raise ValueError("unterminated configuration comment")
                index = end + 2
            for pos in range(start, index):
                if chars[pos] not in "\r\n":
                    chars[pos] = " "
            continue
        index += 1
    return "".join(chars)


def _unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate configuration key")
        result[key] = value
    return result


def parse_roots(text: str) -> Dict[str, str]:
    """Validate administrator JSONC and canonicalize existing external roots."""
    payload = json.loads(_without_comments(text), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict) or set(payload) != {"roots"} or not isinstance(payload["roots"], dict):
        raise ValueError('expected {"roots": {"name": "/absolute/directory"}}')
    roots: Dict[str, str] = {}
    for name, path in payload["roots"].items():
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in ("input", "output"):
            raise ValueError("root IDs must be unique lowercase names; input and output are reserved")
        if not isinstance(path, str) or "\x00" in path or not os.path.isabs(path):
            raise ValueError("external roots must be absolute directory paths")
        resolved = os.path.realpath(path)
        if os.path.dirname(resolved) == resolved or not os.path.isdir(resolved):
            raise ValueError("external roots must be existing directories, not filesystem roots")
        roots[name] = resolved
    return roots


def _read_configuration(directory: Path) -> str:
    """Create exclusively and read a regular file without following symlinks.

    Directory-relative opens on POSIX pin the validated directory even if it
    is renamed during startup. Other platforms use checked absolute paths.
    """
    config = directory / CONFIG_NAME
    directory_fd: Optional[int] = None
    try:
        if os.open in os.supports_dir_fd:
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        target = CONFIG_NAME if directory_fd is not None else str(config)
        flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(CONFIG_TEMPLATE)
        if directory.is_symlink() or config.is_symlink() or not config.is_file():
            raise ValueError("configuration must be a regular file in the system directory")
        descriptor = os.open(target, os.O_RDONLY | flags, dir_fd=directory_fd)
        with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("configuration must be a regular file")
            return stream.read()
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def initialize_roots(directory: Path):
    """Create a template and snapshot roots once, only from extension startup.

    Args:
        directory: ComfyUI's administrator-selected system-user directory.
    """
    global _roots
    if _roots is not None:
        return
    _roots = MappingProxyType({})
    try:
        # Resolve the configured user-directory parent, never a replacement of
        # the system directory or its configuration file.
        directory = directory.parent.resolve() / directory.name
        if directory.is_symlink():
            raise ValueError("configuration directory must not be a symlink")
        directory.mkdir(exist_ok=True)
        config = directory / CONFIG_NAME
        if config.is_symlink() or config.resolve().parent != directory:
            raise ValueError("configuration file must remain in the system directory")
        _roots = MappingProxyType(parse_roots(_read_configuration(directory)))
    except (OSError, UnicodeError, ValueError):
        logger.exception("Cannot initialize config.arisu.jsonc: external roots disabled. Check the system-user file and restart ComfyUI.")


def external_roots() -> Mapping[str, str]:
    """Return the startup snapshot; requests never initialize or reload it."""
    return _roots if _roots is not None else MappingProxyType({})


def image_roots(input_dir: str, output_dir: str) -> Dict[str, str]:
    """Return fixed built-in roots and the startup snapshot of external roots."""
    return {"input": input_dir, "output": output_dir, **external_roots()}


def select_root(roots: Mapping[str, str], name: Any = "input") -> str:
    """Look up a root ID without accepting caller-supplied base directories."""
    if not isinstance(name, str) or name not in roots:
        raise ValueError("unknown image root; select a configured root with Browse")
    return roots[name]
