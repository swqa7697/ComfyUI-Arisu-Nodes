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
import threading
import uuid
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)
CONFIG_NAME = "config.arisu.jsonc"
CONFIG_TEMPLATE = """{
  // Add existing media directories using absolute paths, then restart ComfyUI.
  // Example entry inside roots: "photos": "/data/photos"
  // Only include directories you intend to share with clients of this server.
  // Do not add a trailing comma after the last entry.
  "roots": {},

  // Managed by the Agents settings UI; manual editing is not recommended.
  "workbench": {}
}
"""
_config_lock = threading.RLock()
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
    payload = parse_configuration(text)
    if not isinstance(payload.get("roots"), dict):
        raise ValueError('expected {"roots": {"name": "/absolute/directory"}}')  # noqa: TRY004 - invalid JSON data
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


def parse_configuration(text: str) -> Dict[str, Any]:
    """Parse shared JSONC, rejecting ambiguous keys and malformed documents."""
    payload = json.loads(_without_comments(text), object_pairs_hook=_unique_object)
    if not isinstance(payload, dict):
        raise ValueError("configuration must be an object")  # noqa: TRY004 - invalid JSON data
    return payload


def _set_value(text: str, keys: Tuple[str, ...], value: Any) -> str:
    """Patch one JSONC value, preserving surrounding comments and unknown fields."""
    clean = _without_comments(text)
    decoder = json.JSONDecoder()
    index = clean.index("{") + 1
    last_end = index
    populated = False
    while True:
        while clean[index].isspace():
            index += 1
        if clean[index] == "}":
            nested = value
            for key in reversed(keys[1:]):
                nested = {key: nested}
            addition = "\n  " + json.dumps(keys[0]) + ": " + json.dumps(nested, ensure_ascii=False)
            if keys[0] == "workbench":
                addition = "\n  // Managed by the Agents settings UI; manual editing is not recommended." + addition
            if populated:
                text = text[:last_end] + "," + text[last_end:]
                index += 1
            return text[:index] + addition + "\n" + text[index:]
        key, index = decoder.raw_decode(clean, index)
        while clean[index].isspace() or clean[index] == ":":
            index += 1
        start = index
        current, end = decoder.raw_decode(clean, start)
        if key == keys[0]:
            if len(keys) > 1:
                if not isinstance(current, dict):
                    raise ValueError("configuration section must be an object")
                replacement = _set_value(text[start:end], keys[1:], value)
            else:
                replacement = json.dumps(value, ensure_ascii=False)
            return text[:start] + replacement + text[end:]
        populated = True
        last_end = end
        index = end
        while clean[index].isspace():
            index += 1
        if clean[index] == ",":
            index += 1


def read_configuration(directory: Path) -> Dict[str, Any]:
    """Read the fixed shared configuration; only startup creates its template."""
    with _config_lock:
        return parse_configuration(_read_configuration(directory, create=False))


def save_workbench_preferences(directory: Path, updates: Dict[str, Any]):
    """Atomically patch only Workbench preferences, without reloading root grants."""
    with _config_lock:
        original = _read_configuration(directory, create=False)
        parse_configuration(original)
        updated = original
        for agent, preferences in updates.items():
            if preferences:
                for key, value in preferences.items():
                    updated = _set_value(updated, ("workbench", agent, key), value)
            else:
                updated = _set_value(updated, ("workbench", agent), {})
        parse_configuration(updated)
        directory_fd: Optional[int] = None
        temp = "config-" + uuid.uuid4().hex + ".tmp"
        target = str(directory / temp)
        destination = str(directory / CONFIG_NAME)
        created = False
        try:
            if os.open in os.supports_dir_fd:
                directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                target, destination = temp, CONFIG_NAME
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory_fd)
            created = True
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                stream.write(updated)
                stream.flush()
                os.fsync(stream.fileno())
            if _read_configuration(directory, create=False) != original:
                raise ValueError("configuration changed while saving; retry")
            os.replace(target, destination, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        finally:
            try:
                if created:
                    os.unlink(target, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            if directory_fd is not None:
                os.close(directory_fd)


def _read_configuration(directory: Path, create: bool = True) -> str:
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
        if create:
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
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as stream:
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
        skills = directory / "skills"
        try:
            if not skills.is_symlink():
                skills.mkdir(exist_ok=True)
        except OSError:
            logger.exception("Cannot create the custom skills directory in the system-user directory.")
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
