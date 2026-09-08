"""Tests for the ComfyUI-free layer of the common node family."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.arisu_nodes.common.core import NO_UPSCALE, PreviewRef, SaveRequest, join_path, parse_save_request, preview_file_path


def test_join_path_skips_blanks_and_trims_separators():
    cases = [
        (["minimax_h3", "test"], "minimax_h3/test"),
        (["minimax_h3", "", "   ", "test"], "minimax_h3/test"),
        ([" /videos/ ", "/h3_clip"], "videos/h3_clip"),
        (["a/b", "c"], "a/b/c"),
        (["", "   "], ""),
        ([], ""),
    ]
    for segments, expected in cases:
        assert join_path(segments) == expected, f"case={segments!r}"


def test_parse_save_request_validates_the_button_payload():
    image = {"filename": "a.png", "subfolder": "", "type": "temp", "id": "asset-id-is-ignored"}
    assert parse_save_request({"images": [image], "path": " shots/a "}) == SaveRequest(
        previews=(PreviewRef("a.png", "", "temp"),), path="shots/a", upscale_model=NO_UPSCALE
    )
    # "a/../b" stays inside the output directory; only an escaping ".." is refused
    assert parse_save_request({"images": [image], "path": "a/../b", "upscale_model": "4x.pth"}).upscale_model == "4x.pth"

    bad = [
        ("not an object", []),
        ("no images", {"images": [], "path": "a"}),
        ("image not an object", {"images": ["a.png"], "path": "a"}),
        ("filename missing", {"images": [{"subfolder": "", "type": "temp"}], "path": "a"}),
        ("not a temp preview", {"images": [{**image, "type": "output"}], "path": "a"}),
        ("blank path", {"images": [image], "path": "  "}),
        ("absolute path", {"images": [image], "path": "/etc/passwd"}),
        ("escaping path", {"images": [image], "path": "a/../../b"}),
        ("blank model", {"images": [image], "path": "a", "upscale_model": ""}),
    ]
    for case, payload in bad:
        try:
            parse_save_request(payload)
        except (TypeError, ValueError):
            continue
        pytest.fail(f"case={case!r} was accepted")


def test_preview_file_path_stays_inside_the_base_directory(tmp_path: Path):
    base = str(tmp_path)
    assert preview_file_path(base, PreviewRef("a.png", "sub", "temp")) == str(tmp_path / "sub" / "a.png")
    # only the basename of the filename counts, like ComfyUI's /view
    assert preview_file_path(base, PreviewRef("dir/a.png", "", "temp")) == str(tmp_path / "a.png")

    escaping = [
        PreviewRef("../a.png", "", "temp"),
        PreviewRef("/a.png", "", "temp"),
        PreviewRef("", "", "temp"),
        PreviewRef("a.png", "..", "temp"),
        PreviewRef("a.png", "/etc", "temp"),
    ]
    for ref in escaping:
        try:
            preview_file_path(base, ref)
        except ValueError:
            continue
        pytest.fail(f"case={ref!r} was accepted")
