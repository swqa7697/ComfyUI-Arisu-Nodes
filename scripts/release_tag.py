"""Release tag on the latest ``main``: annotated ``vX.Y.Z`` tag + push.

The version comes from ``pyproject.toml`` at HEAD; the tag message is
``Release vX.Y.Z`` over that version's ``CHANGELOG.md`` section. Pushing the
tag triggers ``.github/workflows/publish_node.yml`` (Comfy registry publish),
so the preview must pass a rendered CAPTCHA.

Rejects when: not on ``main``; HEAD is not ``origin/main``; HEAD already carries
a ``vX.Y.Z`` tag; the tag exists locally or on origin; the CHANGELOG at HEAD has
no ``[X.Y.Z]`` section.

Usage: ``release_tag.py`` — run via ``make tag``.
"""

from __future__ import annotations

from release_common import (
    CHANGELOG,
    PYPROJECT,
    TAG_RE,
    ReleaseError,
    changelog_section,
    confirm_captcha,
    current_branch,
    enter_repo_root,
    fail,
    git,
    git_passthrough,
    info,
    ok,
    parse_version,
    require_tty,
    tag_message,
    tag_name,
)


def main():
    enter_repo_root()
    require_tty("Creating a release tag")

    branch = current_branch()
    if branch != "main":
        fail(f"Release tags are created on main, not '{branch}'.")

    info("Fetching origin/main and tags ...")
    git("fetch", "--quiet", "--tags", "origin", "main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        fail("HEAD is not origin/main — only the latest main gets tagged.")

    try:
        version = parse_version(git("show", f"HEAD:{PYPROJECT}"))
        section = changelog_section(git("show", f"HEAD:{CHANGELOG}"), version)
    except ReleaseError as exc:
        fail(f"{exc} Is HEAD a merged release commit?")
    name = tag_name(version)

    tagged = [tag for tag in git("tag", "--points-at", "HEAD").splitlines() if TAG_RE.match(tag)]
    if tagged:
        fail(f"HEAD is already tagged: {', '.join(tagged)}.")
    if git("tag", "--list", name) or git("ls-remote", "--tags", "origin", f"refs/tags/{name}"):
        fail(f"{name} already exists; bump the version before tagging again.")

    message = tag_message(version, section)
    print(f"\n  {name}  ->  {git('log', '-1', '--format=%h %s', 'HEAD')}\n")
    print("\n".join(f"  {line}" for line in message.splitlines()))
    confirm_captcha("Confirming the tag")

    git("tag", "-a", name, "-F", "-", input_text=message)
    git_passthrough("push", "origin", name)
    ok(f"Pushed {name} to origin; publish_node.yml publishes it to the Comfy registry.")


if __name__ == "__main__":
    main()
