"""Tests for the pure helpers in scripts/release_common.py (no git, no filesystem)."""

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


# ── parse_version / bump_version / set_version ───────────────────────────────
def test_parse_version_reads_the_project_version():
    assert parse_version(PYPROJECT) == "0.1.0"


def test_parse_version_rejects_missing_line():
    with pytest.raises(ReleaseError, match="no `version"):
        parse_version("[project]\nname = 'x'\n")


def test_parse_version_rejects_duplicate_lines():
    with pytest.raises(ReleaseError, match="more than one"):
        parse_version(PYPROJECT + '\n[tool.other]\nversion = "9.9.9"\n')


@pytest.mark.parametrize(("part", "expected"), [("major", "2.0.0"), ("minor", "1.3.0"), ("patch", "1.2.4")])
def test_bump_version_resets_lower_parts(part, expected):
    assert bump_version("1.2.3", part) == expected


def test_bump_version_rejects_unknown_part():
    with pytest.raises(ReleaseError, match="unknown part"):
        bump_version("1.2.3", "micro")


def test_bump_version_rejects_non_semver():
    with pytest.raises(ReleaseError, match="not X.Y.Z"):
        bump_version("1.2", "patch")


def test_set_version_changes_only_the_version_line():
    rewritten = set_version(PYPROJECT, "0.2.0")
    changed = [(a, b) for a, b in zip(PYPROJECT.splitlines(), rewritten.splitlines()) if a != b]
    assert changed == [('version = "0.1.0"', 'version = "0.2.0"')]
    assert parse_version(rewritten) == "0.2.0"


# ── changelog_section ────────────────────────────────────────────────────────
def test_changelog_section_stops_at_next_heading():
    section = changelog_section(CHANGELOG, "Unreleased")
    assert section.startswith("### Added")
    assert section.endswith("- Fix the widget order.")
    assert "[0.1.0]" not in section


def test_changelog_section_last_section_runs_to_eof():
    assert changelog_section(CHANGELOG, "0.1.0") == "### Added\n\n- Initial release."


def test_changelog_section_heading_without_date():
    assert changelog_section("## [1.0.0]\n\n- Done.\n", "1.0.0") == "- Done."


def test_changelog_section_rejects_missing_heading():
    with pytest.raises(ReleaseError, match=r"no `## \[9\.9\.9\]`"):
        changelog_section(CHANGELOG, "9.9.9")


# ── roll_changelog ───────────────────────────────────────────────────────────
def test_roll_changelog_renames_unreleased_and_opens_a_new_one():
    rolled = roll_changelog(CHANGELOG, "0.2.0", "2026-09-05")
    assert "## [Unreleased]\n\n## [0.2.0] - 2026-09-05\n" in rolled
    assert changelog_section(rolled, "0.2.0") == changelog_section(CHANGELOG, "Unreleased")
    assert changelog_section(rolled, "Unreleased") == ""
    assert changelog_section(rolled, "0.1.0") == changelog_section(CHANGELOG, "0.1.0")


def test_roll_changelog_rejects_missing_unreleased():
    with pytest.raises(ReleaseError, match=r"no `## \[Unreleased\]`"):
        roll_changelog("# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- x\n", "0.2.0", "2026-09-05")


def test_roll_changelog_rejects_headings_without_entries():
    text = "# Changelog\n\n## [Unreleased]\n\n### Added\n\n## [0.1.0] - 2026-01-01\n\n- x\n"
    with pytest.raises(ReleaseError, match="nothing under"):
        roll_changelog(text, "0.2.0", "2026-09-05")


def test_roll_changelog_twice_is_refused():
    rolled = roll_changelog(CHANGELOG, "0.2.0", "2026-09-05")
    with pytest.raises(ReleaseError, match="nothing under"):
        roll_changelog(rolled, "0.3.0", "2026-09-06")


# ── Formats ──────────────────────────────────────────────────────────────────
def test_release_subject_matches_its_regex():
    assert RELEASE_SUBJECT_RE.match(release_subject("0.2.0"))


@pytest.mark.parametrize("subject", ["chore: bump version to 1.2", "chore: bump version to 1.2.3 again", "feat: bump version to 1.2.3"])
def test_release_subject_regex_rejects_near_misses(subject):
    assert RELEASE_SUBJECT_RE.match(subject) is None


def test_tag_name_matches_its_regex():
    assert tag_name("0.2.0") == "v0.2.0"
    assert TAG_RE.match(tag_name("0.2.0"))
    assert TAG_RE.match("v2026-09-05") is None


def test_tag_message_titles_the_section():
    message = tag_message("0.2.0", "### Added\n\n- Thing.")
    assert message == "Release v0.2.0\n\n### Added\n\n- Thing.\n"


# ── changed_paths ────────────────────────────────────────────────────────────
def test_changed_paths_parses_porcelain_including_renames():
    porcelain = " M pyproject.toml\nM  CHANGELOG.md\nMM uv.lock\nR  old.py -> new.py\n"
    assert changed_paths(porcelain) == ["pyproject.toml", "CHANGELOG.md", "uv.lock", "new.py"]


def test_changed_paths_empty_output():
    assert changed_paths("") == []
