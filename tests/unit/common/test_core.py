"""Tests for the ComfyUI-free layer of the common node family."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.arisu_nodes.common.core import (
    NO_UPSCALE,
    BrowseRequest,
    CropBox,
    DirectoryListing,
    PreviewRef,
    ResizePlan,
    SaveRequest,
    TreeLevel,
    ViewRequest,
    browse_directory,
    crop_box,
    join_path,
    parse_browse_request,
    parse_crop,
    parse_pad_color,
    parse_save_request,
    parse_view_request,
    preview_file_path,
    resize_plan,
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
    assert parse_save_request({"images": [image], "path": "b", "upscale_model": "4x.pth"}).upscale_model == "4x.pth"

    bad = [
        ("not an object", []),
        ("no images", {"images": [], "path": "a"}),
        ("image not an object", {"images": ["a.png"], "path": "a"}),
        ("filename missing", {"images": [{"subfolder": "", "type": "temp"}], "path": "a"}),
        ("not a temp preview", {"images": [{**image, "type": "output"}], "path": "a"}),
        ("blank path", {"images": [image], "path": "  "}),
        ("absolute path", {"images": [image], "path": "/etc/passwd"}),
        ("escaping path", {"images": [image], "path": "a/../../b"}),
        ("normalized traversal", {"images": [image], "path": "a/../b"}),
        ("oversized batch", {"images": [image] * 257, "path": "a"}),
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
    # A filename must already be a basename; never silently rewrite hostile references.

    escaping = [
        PreviewRef("../a.png", "", "temp"),
        PreviewRef("dir/a.png", "", "temp"),
        PreviewRef("dir\\a.png", "", "temp"),
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


def test_image_path_helpers_resolve_and_refuse(tmp_path: Path):
    base = tmp_path / "input"
    root = base / "pics"
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"sentinel")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "secret.png").symlink_to(outside / "secret.png")
    (root / "ok.jpg").write_bytes(b"")
    (root / ".hidden.png").write_bytes(b"")
    (root / "notes.txt").write_text("x")
    (root / "payload.svg").write_text("<svg/>")
    (root / "art").mkdir()
    (base / "inside").symlink_to(root, target_is_directory=True)
    input_dir = str(base)
    assert resolve_image_path("pics\\ok.jpg", input_dir) == str(root / "ok.jpg")
    assert resolve_image_path("inside/ok.jpg", input_dir) == str(root / "ok.jpg")
    for value in [
        "",
        "   ",
        None,
        3,
        "../outside/secret.png",
        "pics/../pics/ok.jpg",
        str(root / "ok.jpg"),
        "~/ok.png",
        "C:foo.png",
        "C:\\foo.png",
        "\\\\server\\share\\a.png",
        "a.png:secret",
        "x\x00.png",
        "pics/escape/secret.png",
        "pics/secret.png",
        "NUL.png",
        "dir./a.png",
    ]:
        with pytest.raises((TypeError, ValueError)):
            resolve_image_path(value, input_dir)
    assert parse_browse_request({}, input_dir) == BrowseRequest(input_dir, True)
    assert parse_browse_request({"path": "", "tree": "0"}, input_dir) == BrowseRequest(input_dir, False)
    assert parse_view_request({"path": "pics/ok.jpg"}, input_dir) == ViewRequest(str(root / "ok.jpg"), None)
    for raw, expected in [("8", 16), ("256", 256), ("99999", 4096)]:
        assert parse_view_request({"path": "pics/ok.jpg", "max": raw}, input_dir).max_size == expected, f"case={raw!r}"
    for query in [{}, {"path": "../secret.png"}, {"path": "pics/ok.jpg", "max": "big"}, {"path": "pics/ok.jpg", "crop": "1,2"}]:
        with pytest.raises(ValueError):
            parse_view_request(query, input_dir)
    for value, expected in [("", None), (None, None), ("1,2,3,4", CropBox(1, 2, 3, 4))]:
        assert parse_crop(value) == expected, f"case={value!r}"
    for value in ["1,2,3", "1,2,3,4,5", "-1,0,3,4", "0,0,0,4", "0,0,4,0", "a,b,c,d", 7]:
        with pytest.raises((TypeError, ValueError)):
            parse_crop(value)
    assert crop_box(CropBox(1, 2, 3, 4), (10, 10)) == (1, 2, 4, 6)
    assert crop_box(CropBox(4, 2, 10, 10), (6, 4)) == (4, 2, 6, 4)
    assert crop_box(CropBox(0, 0, 9, 9), (6, 4)) is None
    with pytest.raises(ValueError):
        crop_box(CropBox(6, 0, 1, 1), (6, 4))
    listing = browse_directory(str(root), input_dir)
    assert listing == DirectoryListing("pics", "", ("art",), ("ok.jpg",), (TreeLevel("", ("inside", "pics")),))
    assert browse_directory(str(root / "ok.jpg"), input_dir) == listing
    assert browse_directory(str(root), input_dir, with_tree=False).ancestors == ()
    assert browse_directory(input_dir, input_dir).parent is None
    with pytest.raises(ValueError):
        browse_directory(str(outside), input_dir)
    with pytest.raises(FileNotFoundError):
        browse_directory(str(root / "nope"), input_dir)


def test_resize_plan_covers_every_mode():
    # a 3:2 source; each case is (width, height, mode, crop_position, divisible_by) -> the plan
    source = (600, 400)
    cases = [
        # stretch: exactly the request, 0 taking the source side, snapped down to the grid but never below one multiple
        ((300, 300, "stretch", "center", 0), ResizePlan(None, (300, 300), (300, 300), (0, 0))),
        ((0, 0, "stretch", "center", 0), ResizePlan(None, (600, 400), (600, 400), (0, 0))),
        ((0, 100, "stretch", "center", 0), ResizePlan(None, (600, 100), (600, 100), (0, 0))),
        ((301, 301, "stretch", "center", 8), ResizePlan(None, (296, 296), (296, 296), (0, 0))),
        ((5, 5, "stretch", "center", 8), ResizePlan(None, (8, 8), (8, 8), (0, 0))),
        # resize: fit inside the request; a 0 side follows the aspect ratio; the fitted size is what the grid snaps
        ((300, 300, "resize", "center", 0), ResizePlan(None, (300, 200), (300, 200), (0, 0))),
        ((0, 100, "resize", "center", 0), ResizePlan(None, (150, 100), (150, 100), (0, 0))),
        ((100, 0, "resize", "center", 0), ResizePlan(None, (100, 67), (100, 67), (0, 0))),
        ((0, 0, "resize", "center", 0), ResizePlan(None, (600, 400), (600, 400), (0, 0))),
        ((300, 300, "resize", "center", 16), ResizePlan(None, (288, 192), (288, 192), (0, 0))),
        # pad: the canvas is the snapped request, the image fits inside it, the position anchors it along its
        # own axis and the other axis is centred; a derived side leaves no room, so the canvas is the image
        ((300, 300, "pad", "center", 0), ResizePlan(None, (300, 200), (300, 300), (0, 50))),
        ((300, 300, "pad", "top", 0), ResizePlan(None, (300, 200), (300, 300), (0, 0))),
        ((300, 300, "pad", "bottom", 0), ResizePlan(None, (300, 200), (300, 300), (0, 100))),
        ((100, 500, "pad", "right", 0), ResizePlan(None, (100, 67), (100, 500), (0, 216))),
        ((1000, 500, "pad", "left", 16), ResizePlan(None, (744, 496), (992, 496), (0, 0))),
        ((0, 200, "pad", "center", 0), ResizePlan(None, (300, 200), (300, 200), (0, 0))),
        # crop: the largest source box of the canvas's aspect, anchored, then scaled to the canvas; a matching aspect cuts nothing
        ((300, 300, "crop", "center", 0), ResizePlan((100, 0, 400, 400), (300, 300), (300, 300), (0, 0))),
        ((300, 300, "crop", "right", 0), ResizePlan((200, 0, 400, 400), (300, 300), (300, 300), (0, 0))),
        ((600, 100, "crop", "bottom", 0), ResizePlan((0, 300, 600, 100), (600, 100), (600, 100), (0, 0))),
        ((300, 200, "crop", "center", 0), ResizePlan(None, (300, 200), (300, 200), (0, 0))),
        ((0, 0, "crop", "center", 0), ResizePlan(None, (600, 400), (600, 400), (0, 0))),
    ]
    for case, expected in cases:
        assert resize_plan(source, *case) == expected, f"case={case!r}"
    # an unknown mode (the dropped total_pixels among them) or position is refused
    for case in [(300, 300, "total_pixels", "center", 0), (300, 300, "shrink", "center", 0), (300, 300, "pad", "middle", 0)]:
        with pytest.raises(ValueError):
            resize_plan(source, *case)


def test_parse_pad_color_accepts_every_colour_form():
    # r, g, b in 0-255 unless a decimal point makes it 0-1; hex with or without alpha; one grey value; clamped channels
    cases = [
        ("0, 0, 0", (0.0, 0.0, 0.0)),
        ("255, 0, 0", (1.0, 0.0, 0.0)),
        ("1.0, 0.5, 0", (1.0, 0.5, 0.0)),
        ("1, 1, 1", (1 / 255, 1 / 255, 1 / 255)),
        (" #ff8000 ", (1.0, 128 / 255, 0.0)),
        ("#F80", (1.0, 136 / 255, 0.0)),
        ("#ff800080", (1.0, 128 / 255, 0.0)),
        ("128", (128 / 255,) * 3),
        ("0.5", (0.5,) * 3),
        ("300, -5, 0", (1.0, 0.0, 0.0)),
    ]
    for value, expected in cases:
        assert parse_pad_color(value) == pytest.approx(expected), f"case={value!r}"
    # a word is a colour name, left to Pillow on the ComfyUI side
    assert parse_pad_color("white") is None
    for value in ["", "  ", "1, 2", "1, 2, 3, 4", "a, b, c", "#12345", "12 34", "inf, 0, 0", "ff8000", 7]:
        with pytest.raises((TypeError, ValueError)):
            parse_pad_color(value)
