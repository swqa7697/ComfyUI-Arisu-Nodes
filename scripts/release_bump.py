"""Bump the version: rewrite ``pyproject.toml``, roll ``CHANGELOG.md``, refresh ``uv.lock``.

No git writes; ``make release-commit`` commits the result. Both rewritten texts
are computed before anything is written, so a refusal leaves the tree untouched.

Rejects when: any of the three release files is already modified; ``[Unreleased]``
has no entries. Warns when run on ``main``, where ``release_commit.py`` refuses.

Usage: ``release_bump.py {major,minor,patch}`` — run via ``make bump-<part>``.
"""

from __future__ import annotations

import argparse

from release_common import (
    CHANGELOG,
    PARTS,
    PYPROJECT,
    RELEASE_FILES,
    UNRELEASED,
    ReleaseError,
    bump_version,
    changed_paths,
    current_branch,
    enter_repo_root,
    fail,
    git,
    info,
    ok,
    parse_version,
    roll_changelog,
    run_uv_lock,
    set_version,
    today,
    warn,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("part", choices=PARTS, help="which version component to bump")
    return parser.parse_args()


def main():
    args = parse_args()
    root = enter_repo_root()

    dirty = changed_paths(git("status", "--porcelain", "--untracked-files=no", "--", *RELEASE_FILES))
    if dirty:
        fail(f"{', '.join(dirty)} already modified; commit or stash first.")

    day = today()
    pyproject = (root / PYPROJECT).read_text()
    changelog = (root / CHANGELOG).read_text()
    try:
        current = parse_version(pyproject)
        new = bump_version(current, args.part)
        new_pyproject = set_version(pyproject, new)
        new_changelog = roll_changelog(changelog, new, day)
    except ReleaseError as exc:
        fail(str(exc))

    if current_branch() == "main":
        warn(f"on main, where release-commit refuses; run: git switch -c release/{new}")

    (root / PYPROJECT).write_text(new_pyproject)
    info(f"bumped {current} -> {new}")
    (root / CHANGELOG).write_text(new_changelog)
    info(f"rolled CHANGELOG [{UNRELEASED}] -> [{new}] - {day} and opened a new empty [{UNRELEASED}]")
    info(f"re-locking so uv.lock records version {new} ...")
    run_uv_lock()
    ok("done. next: make release-commit")


if __name__ == "__main__":
    main()
