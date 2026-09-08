"""Tests for the pure helpers in scripts/release_common.py (no git, no filesystem)."""

from __future__ import annotations

import pytest

from release_common import (
    RELEASE_SUBJECT_RE,
    TAG_RE,
    ReleaseError,
    bump_version,
    changed_paths,
    changelog_section,
    parse_version,
    release_subject,
    roll_changelog,
    set_version,
    tag_message,
    tag_name,
)

PYPROJECT = """[build-system]
requires = ["setuptools>=84"]

[project]
name = "arisu_nodes"
version = "0.1.0"
description = "A package of useful nodes."
requires-python = ">=3.10"
"""

CHANGELOG = """# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- Add the `ArisuExample` node.
- Add the extension entrypoint.

### Fixed

- Fix the widget order.

## [0.1.0] - 2026-01-01

### Added

- Initial release.
"""


def test_version_line_is_parsed_and_rewritten_in_place():
    assert parse_version(PYPROJECT) == "0.1.0"

    rewritten = set_version(PYPROJECT, "0.2.0")
    changed = [(a, b) for a, b in zip(PYPROJECT.splitlines(), rewritten.splitlines()) if a != b]
    assert changed == [('version = "0.1.0"', 'version = "0.2.0"')]
    assert parse_version(rewritten) == "0.2.0"

    with pytest.raises(ReleaseError, match="no `version"):
        parse_version("[project]\nname = 'x'\n")
    with pytest.raises(ReleaseError, match="more than one"):
        parse_version(PYPROJECT + '\n[tool.other]\nversion = "9.9.9"\n')


def test_bump_version_resets_lower_parts_and_rejects_bad_input():
    for part, expected in [("major", "2.0.0"), ("minor", "1.3.0"), ("patch", "1.2.4")]:
        assert bump_version("1.2.3", part) == expected, f"case={part!r}"
    with pytest.raises(ReleaseError, match="unknown part"):
        bump_version("1.2.3", "micro")
    with pytest.raises(ReleaseError, match="not X.Y.Z"):
        bump_version("1.2", "patch")


def test_changelog_section_is_bounded_by_headings():
    section = changelog_section(CHANGELOG, "Unreleased")
    assert section.startswith("### Added")
    assert section.endswith("- Fix the widget order.")
    assert "[0.1.0]" not in section

    # the last section runs to EOF, and a heading needs no date
    assert changelog_section(CHANGELOG, "0.1.0") == "### Added\n\n- Initial release."
    assert changelog_section("## [1.0.0]\n\n- Done.\n", "1.0.0") == "- Done."

    with pytest.raises(ReleaseError, match=r"no `## \[9\.9\.9\]`"):
        changelog_section(CHANGELOG, "9.9.9")


def test_roll_changelog_moves_unreleased_under_a_dated_heading_once():
    rolled = roll_changelog(CHANGELOG, "0.2.0", "2026-09-05")
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-09-05\n" in rolled
    assert changelog_section(rolled, "0.2.0") == changelog_section(CHANGELOG, "Unreleased")
    assert changelog_section(rolled, "Unreleased") == ""
    assert changelog_section(rolled, "0.1.0") == changelog_section(CHANGELOG, "0.1.0")

    # a second roll finds nothing to release; neither does a heading with no entries, or no [Unreleased] at all
    with pytest.raises(ReleaseError, match="nothing under"):
        roll_changelog(rolled, "0.3.0", "2026-09-06")
    with pytest.raises(ReleaseError, match="nothing under"):
        roll_changelog("# Changelog\n\n## [Unreleased]\n\n### Added\n\n## [0.1.0] - 2026-01-01\n\n- x\n", "0.2.0", "2026-09-05")
    with pytest.raises(ReleaseError, match=r"no `## \[Unreleased\]`"):
        roll_changelog("# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- x\n", "0.2.0", "2026-09-05")


def test_release_subject_and_tag_formats_satisfy_their_gates():
    assert RELEASE_SUBJECT_RE.match(release_subject("0.2.0"))
    for subject in ("chore: bump version to 1.2", "chore: bump version to 1.2.3 again", "feat: bump version to 1.2.3"):
        assert RELEASE_SUBJECT_RE.match(subject) is None, f"case={subject!r}"

    assert tag_name("0.2.0") == "v0.2.0"
    assert TAG_RE.match(tag_name("0.2.0"))
    assert TAG_RE.match("v2026-09-05") is None
    assert tag_message("0.2.0", "### Added\n\n- Thing.") == "Release v0.2.0\n\n### Added\n\n- Thing.\n"


def test_changed_paths_parses_porcelain_including_renames_and_empty_output():
    porcelain = " M pyproject.toml\nM  CHANGELOG.md\nMM uv.lock\nR  old.py -> new.py\n"
    assert changed_paths(porcelain) == ["pyproject.toml", "CHANGELOG.md", "uv.lock", "new.py"]
    assert changed_paths("") == []
