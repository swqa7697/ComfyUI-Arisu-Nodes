"""Release commit on a release branch: commit the version bump and push.

The subject is ``chore: bump version to X.Y.Z`` (``RELEASE_SUBJECT_RE`` in
``release_common.py``); ``/release-pr`` validates it before opening the PR.

Rejects when: on ``main``; nothing changed; anything other than ``pyproject.toml``,
``CHANGELOG.md``, or ``uv.lock`` changed; the version equals HEAD's; the
CHANGELOG lacks the ``[X.Y.Z]`` section; ``origin/<branch>`` exists but is not
HEAD (behind, the push would be refused; ahead, unrelated local commits would
ride along with the release commit).

Usage: ``release_commit.py [-y|--yes]`` — run via ``make release-commit [YES=1]``.
"""

from __future__ import annotations

import argparse

from release_common import (
    CHANGELOG,
    LOCKFILE,
    PYPROJECT,
    RELEASE_FILES,
    ReleaseError,
    changed_paths,
    changelog_section,
    confirm_yes_no,
    current_branch,
    enter_repo_root,
    fail,
    git,
    git_passthrough,
    info,
    ok,
    parse_version,
    release_subject,
    require_tty,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    return parser.parse_args()


def main():
    args = parse_args()
    root = enter_repo_root()

    branch = current_branch()
    if branch == "main":
        fail("Release commits go on a release branch, not main; run: git switch -c release/<X.Y.Z>")

    paths = changed_paths(git("status", "--porcelain", "--untracked-files=no"))
    if not paths:
        fail("Nothing changed — run make bump-patch|minor|major first.")
    others = [path for path in paths if path not in RELEASE_FILES]
    if others:
        fail(f"only {', '.join(RELEASE_FILES)} may change; also changed: {', '.join(others)}.")

    try:
        head_version = parse_version(git("show", f"HEAD:{PYPROJECT}"))
        version = parse_version((root / PYPROJECT).read_text())
        if version == head_version:
            fail(f"{PYPROJECT} version {version} equals HEAD's; run make bump-* first.")
        changelog_section((root / CHANGELOG).read_text(), version)
    except ReleaseError as exc:
        fail(str(exc))

    info(f"Checking origin/{branch} ...")
    remote = git("ls-remote", "--heads", "origin", branch)
    if remote:
        if remote.split()[0] != git("rev-parse", "HEAD"):
            fail(f"HEAD is not origin/{branch} — the release commit must be the only push.")
    else:
        info(f"origin/{branch} does not exist yet; the push will create it.")

    subject = release_subject(version)
    print(f"\n  {subject}\n")
    print(git("diff", "HEAD", "--", PYPROJECT, CHANGELOG))
    print(git("diff", "HEAD", "--stat", "--", LOCKFILE))
    print()

    if not args.yes:
        require_tty("Confirming the release commit (or pass YES=1)")
        if not confirm_yes_no(f"Commit and push to origin/{branch}?"):
            fail("Aborted.")

    git("add", "--", *RELEASE_FILES)
    git("commit", "--quiet", "-m", subject)
    git_passthrough("push", "-u", "origin", branch)
    ok(f"Pushed {git('rev-parse', '--short', 'HEAD')} to origin/{branch}: {subject}")
    info("next: open the release PR with /release-pr")


if __name__ == "__main__":
    main()
