"""Tests for the ComfyUI-free layer of the common node family."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.arisu_nodes.common.core import (
    NO_UPSCALE,
    DirectoryListing,
    PreviewRef,
    SaveRequest,
    ViewRequest,
    browse_directory,
    join_path,
    parse_browse_request,
    parse_save_request,
    parse_view_request,
    preview_file_path,
    resolve_image_path,
)


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


def test_image_path_helpers_resolve_and_refuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    input_dir = str(tmp_path / "input")
    # the three forms of the path widget: relative to the input directory, ~, absolute
    resolved = [
        ("sub/a.png", str(tmp_path / "input" / "sub" / "a.png")),
        ("  sub/a.png  ", str(tmp_path / "input" / "sub" / "a.png")),
        ("~/b.jpg", str(tmp_path / "b.jpg")),
        ("/abs/c.webp", "/abs/c.webp"),
        ("/abs/../c.webp", "/c.webp"),
    ]
    for value, expected in resolved:
        assert resolve_image_path(value, input_dir) == expected, f"case={value!r}"
    for value in ["", "   ", None, 3]:
        with pytest.raises(ValueError):
            resolve_image_path(value, input_dir)

    # a browse request defaults to the input directory; a view request wants an absolute image path
    assert parse_browse_request({}, input_dir) == input_dir
    assert parse_browse_request({"path": "  "}, input_dir) == input_dir
    assert parse_browse_request({"path": "~/pics"}, input_dir) == str(tmp_path / "pics")
    assert parse_view_request({"path": "/x/a.png"}) == ViewRequest("/x/a.png", None)
    clamped = [("8", 16), ("256", 256), ("99999", 4096)]
    for raw, expected in clamped:
        assert parse_view_request({"path": "/x/a.png", "max": raw}).max_size == expected, f"case={raw!r}"
    bad = [
        ("relative", {"path": "a.png"}),
        ("missing", {}),
        ("not an image", {"path": "/x/notes.txt"}),
        ("bad max", {"path": "/x/a.png", "max": "big"}),
    ]
    for case, query in bad:
        try:
            parse_view_request(query)
        except ValueError:
            continue
        pytest.fail(f"case={case!r} was accepted")

    # a listing: subdirectories and image files only, hidden entries skipped, sorted case-insensitively
    root = tmp_path / "pics"
    for folder in ["Zoo", "art", ".hidden"]:
        (root / folder).mkdir(parents=True)
    for name in ["b.PNG", "a.jpg", ".secret.png", "notes.txt", "clip.mp4"]:
        (root / name).write_bytes(b"")
    listing = browse_directory(str(root))
    assert listing == DirectoryListing(str(root), str(tmp_path), ("art", "Zoo"), ("a.jpg", "b.PNG"))
    # a file path lists the directory holding it, so the dialog opens where the current value lives
    assert browse_directory(str(root / "a.jpg")) == listing
    assert browse_directory("/").parent is None
    with pytest.raises(FileNotFoundError):
        browse_directory(str(root / "nope"))
