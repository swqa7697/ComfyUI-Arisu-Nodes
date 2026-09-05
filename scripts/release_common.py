"""Shared pieces of the release CLIs (release_bump.py, release_commit.py, release_tag.py).

Pure helpers first: version parsing and bumping, CHANGELOG rolling and section
extraction, the release-commit subject and the tag name/message. They raise
``ReleaseError`` and are unit-tested in ``tests/unit/test_release_common.py``.
Then the side-effecting plumbing: logger.sh-shaped output, git wrappers,
``uv lock``, and the interactive gates. Only the CLIs call ``fail``.

Stdlib only and 3.10-compatible (no ``tomllib``; the version is read with a
regex). The Makefile runs these under ``uv run --quiet --no-project python`` so
nothing syncs the project venv between a bump and its release commit.
"""

from __future__ import annotations

import os
import random
import re
import string
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import NoReturn

PYPROJECT = "pyproject.toml"
CHANGELOG = "CHANGELOG.md"
LOCKFILE = "uv.lock"
RELEASE_FILES = (PYPROJECT, CHANGELOG, LOCKFILE)
PARTS = ("major", "minor", "patch")
UNRELEASED = "Unreleased"

VERSION_RE = re.compile(r'^version = "(\d+\.\d+\.\d+)"$', re.MULTILINE)
RELEASE_SUBJECT_RE = re.compile(r"^chore: bump version to \d+\.\d+\.\d+$")
TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")

_TOOL = Path(sys.argv[0]).stem

_DIGIT_FONT: dict[str, list[str]] = {
    "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": [" █ ", "██ ", " █ ", " █ ", "███"],
    "2": ["███", "  █", "███", "█  ", "███"],
    "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"],
    "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"],
    "9": ["███", "█ █", "███", "  █", "███"],
}


class ReleaseError(ValueError):
    """A release file is not in the shape the release flow expects."""


# ── Pure helpers ─────────────────────────────────────────────────────────────
def parse_version(text: str) -> str:
    """Return the ``X.Y.Z`` from the single ``version = "..."`` line in pyproject text.

    Args:
        text: Contents of ``pyproject.toml``.

    Returns:
        The version string.

    Raises:
        ReleaseError: If there is no such line or more than one.
    """
    found = VERSION_RE.findall(text)
    if not found:
        raise ReleaseError(f'{PYPROJECT}: no `version = "X.Y.Z"` line.')
    if len(found) > 1:
        raise ReleaseError(f"{PYPROJECT}: more than one `version = ...` line ({', '.join(found)}).")
    return found[0]


def bump_version(version: str, part: str) -> str:
    """Return ``version`` with ``part`` incremented and the lower parts reset to 0.

    Args:
        version: An ``X.Y.Z`` string.
        part: One of ``PARTS``.

    Returns:
        The bumped ``X.Y.Z`` string.

    Raises:
        ReleaseError: If ``part`` is unknown or ``version`` is not ``X.Y.Z``.
    """
    if part not in PARTS:
        raise ReleaseError(f"unknown part {part!r}; expected one of {', '.join(PARTS)}.")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ReleaseError(f"{version!r} is not X.Y.Z.")
    major, minor, patch = (int(n) for n in version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def set_version(text: str, new_version: str) -> str:
    """Return pyproject text with its ``version`` line set to ``new_version``.

    Everything but that one line is left byte-identical.

    Args:
        text: Contents of ``pyproject.toml``.
        new_version: The ``X.Y.Z`` to write.

    Returns:
        The rewritten text.

    Raises:
        ReleaseError: If ``text`` has no single ``version`` line.
    """
    parse_version(text)
    return VERSION_RE.sub(f'version = "{new_version}"', text, count=1)


def _heading_re(version: str) -> re.Pattern[str]:
    return re.compile(rf"^## \[{re.escape(version)}\](?: - .*)?[ \t]*$", re.MULTILINE)


def changelog_section(text: str, version: str) -> str:
    """Return the body of the ``## [version]`` section of a Keep a Changelog file.

    The body runs from the heading (with or without a `` - YYYY-MM-DD`` suffix)
    to the next ``## `` heading or the end of the file, with surrounding blank
    lines stripped. ``version`` may be ``"Unreleased"``.

    Args:
        text: Contents of ``CHANGELOG.md``.
        version: The bracketed heading text to look up.

    Returns:
        The section body, possibly empty.

    Raises:
        ReleaseError: If the heading is missing.
    """
    match = _heading_re(version).search(text)
    if match is None:
        raise ReleaseError(f"{CHANGELOG}: no `## [{version}]` section.")
    body = text[match.end() :]
    following = re.search(r"^## ", body, re.MULTILINE)
    if following is not None:
        body = body[: following.start()]
    return body.strip("\n")


def roll_changelog(text: str, new_version: str, day: str) -> str:
    """Rename ``## [Unreleased]`` to ``## [new_version] - day`` and open a new empty one above it.

    Args:
        text: Contents of ``CHANGELOG.md``.
        new_version: The ``X.Y.Z`` being released.
        day: The release date as ``YYYY-MM-DD``.

    Returns:
        The rewritten text.

    Raises:
        ReleaseError: If there is no ``[Unreleased]`` heading or it lists no entries.
    """
    section = changelog_section(text, UNRELEASED)
    if re.search(r"^[-*] ", section, re.MULTILINE) is None:
        raise ReleaseError(f"{CHANGELOG}: nothing under [{UNRELEASED}]; add entries before bumping.")
    replacement = f"## [{UNRELEASED}]\n\n## [{new_version}] - {day}"
    return _heading_re(UNRELEASED).sub(replacement, text, count=1)


def release_subject(version: str) -> str:
    """Return the release commit subject for ``version`` (matches ``RELEASE_SUBJECT_RE``)."""
    return f"chore: bump version to {version}"


def tag_name(version: str) -> str:
    """Return the tag name for ``version`` (matches ``TAG_RE``)."""
    return f"v{version}"


def tag_message(version: str, section: str) -> str:
    """Return the annotated-tag message: a ``Release vX.Y.Z`` title over the changelog section."""
    return f"Release {tag_name(version)}\n\n{section}\n"


def changed_paths(porcelain: str) -> list[str]:
    """Return the paths listed by ``git status --porcelain`` output.

    Rename and copy entries (``R  old -> new``) yield the new path.

    Args:
        porcelain: Raw ``git status --porcelain`` output.

    Returns:
        The changed paths in order.
    """
    paths: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if (line[0] in "RC" or line[1] in "RC") and " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


# ── Logging (same "<tool> | <timestamp> | <mark> <message>" shape as logger.sh) ─
def _log(mark: str, msg: str, *, err: bool = False) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stream = sys.stderr if err else sys.stdout
    sys.stdout.flush()
    print(f"{_TOOL} | {stamp} | {mark} {msg}", file=stream, flush=True)


def info(msg: str) -> None:
    """Log a progress line."""
    _log("•", msg)


def ok(msg: str) -> None:
    """Log a success line."""
    _log("✓", msg)


def warn(msg: str) -> None:
    """Log a warning line to stderr."""
    _log("!", msg, err=True)


def fail(msg: str) -> NoReturn:
    """Log an error line to stderr and exit 1."""
    _log("✗", msg, err=True)
    sys.exit(1)


# ── git and uv ───────────────────────────────────────────────────────────────
def git(*args: str, input_text: str | None = None) -> str:
    """Run git, returning stripped stdout; ``fail`` on a non-zero exit."""
    proc = subprocess.run(["git", *args], text=True, capture_output=True, input=input_text)
    if proc.returncode != 0:
        fail(f"git {' '.join(args)} failed:\n{proc.stderr.strip()}")
    return proc.stdout.rstrip("\n")


def git_passthrough(*args: str) -> None:
    """Run git with the terminal attached (push progress, remote messages)."""
    if subprocess.run(["git", *args]).returncode != 0:
        fail(f"git {' '.join(args)} failed.")


def enter_repo_root() -> Path:
    """``chdir`` to the repository root and return it."""
    root = Path(git("rev-parse", "--show-toplevel"))
    os.chdir(root)
    return root


def current_branch() -> str:
    """Return the checked-out branch name; ``fail`` when HEAD is detached."""
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        fail("HEAD is detached; check out a branch first.")
    return branch


def run_uv_lock() -> None:
    """Re-lock the project so ``uv.lock`` records the current pyproject version."""
    if subprocess.run(["uv", "lock", "--quiet"]).returncode != 0:
        fail("uv lock failed.")


def today() -> str:
    """Return the local date as ``YYYY-MM-DD`` (same as ``date +%F``)."""
    return date.today().isoformat()


# ── Interactive gates ────────────────────────────────────────────────────────
def require_tty(action: str) -> None:
    """``fail`` unless stdin is an interactive terminal."""
    if not sys.stdin.isatty():
        fail(f"{action} needs an interactive terminal; aborting.")


def prompt(text: str, default: str = "") -> str:
    """Read one stripped line, returning ``default`` on an empty answer."""
    try:
        answer = input(text).strip()
    except EOFError:
        fail("No input received; aborting.")
    return answer or default


def confirm_yes_no(question: str) -> bool:
    """Ask ``question [y/N]`` and return whether the answer was yes."""
    return prompt(f"{question} [y/N]: ").lower() in ("y", "yes")


def confirm_captcha(action: str) -> None:
    """Gate on a fresh 4-digit code rendered as block glyphs.

    The code is regenerated every run and only readable as rendered text, so
    the confirmation can neither be reflexive nor scripted.
    """
    require_tty(action)
    code = "".join(random.SystemRandom().choice(string.digits) for _ in range(4))
    print()
    for row in range(5):
        print("   " + "   ".join(_DIGIT_FONT[digit][row] for digit in code))
    print()
    if prompt("Type the 4 digits shown above to proceed: ") != code:
        fail("CAPTCHA mismatch; aborting.")
