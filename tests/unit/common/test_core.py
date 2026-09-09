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
    TreeRoot,
    ViewRequest,
    browse_directory,
    crop_box,
    join_path,
    mount_points,
    parse_browse_request,
    parse_crop,
    parse_pad_color,
    parse_save_request,
    parse_view_request,
    preview_file_path,
    resize_plan,
    resolve_image_path,
    tree_roots,
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

    # a browse request defaults to the input directory and wants the tree chain unless tree=0; a view request wants an absolute image path
    assert parse_browse_request({}, input_dir) == BrowseRequest(input_dir, True)
    assert parse_browse_request({"path": "  ", "tree": "0"}, input_dir) == BrowseRequest(input_dir, False)
    assert parse_browse_request({"path": "~/pics"}, input_dir).path == str(tmp_path / "pics")
    assert parse_view_request({"path": "/x/a.png"}) == ViewRequest("/x/a.png", None)
    clamped = [("8", 16), ("256", 256), ("99999", 4096)]
    for raw, expected in clamped:
        assert parse_view_request({"path": "/x/a.png", "max": raw}).max_size == expected, f"case={raw!r}"
    # the crop: four pixel integers, blank for the whole image; its box is cut to the image, the whole image is no box,
    # and one outside the image is refused
    crops = [("", None), ("  ", None), (None, None), ("1,2,3,4", CropBox(1, 2, 3, 4)), (" 1, 2 ,3,4 ", CropBox(1, 2, 3, 4))]
    for value, expected in crops:
        assert parse_crop(value) == expected, f"case={value!r}"
    for value in ["1,2,3", "1,2,3,4,5", "-1,0,3,4", "0,0,0,4", "0,0,4,0", "a,b,c,d", 7]:
        with pytest.raises((TypeError, ValueError)):
            parse_crop(value)
    assert crop_box(CropBox(1, 2, 3, 4), (10, 10)) == (1, 2, 4, 6)
    assert crop_box(CropBox(4, 2, 10, 10), (6, 4)) == (4, 2, 6, 4)
    assert crop_box(CropBox(0, 0, 6, 4), (6, 4)) is None
    assert crop_box(CropBox(0, 0, 9, 9), (6, 4)) is None
    with pytest.raises(ValueError):
        crop_box(CropBox(6, 0, 1, 1), (6, 4))
    assert parse_view_request({"path": "/x/a.png", "crop": "1,2,3,4"}) == ViewRequest("/x/a.png", None, CropBox(1, 2, 3, 4))
    bad = [
        ("relative", {"path": "a.png"}),
        ("missing", {}),
        ("not an image", {"path": "/x/notes.txt"}),
        ("bad max", {"path": "/x/a.png", "max": "big"}),
        ("bad crop", {"path": "/x/a.png", "crop": "1,2"}),
    ]
    for case, query in bad:
        try:
            parse_view_request(query)
        except ValueError:
            continue
        pytest.fail(f"case={case!r} was accepted")

    # a listing: subdirectories and image files only, hidden entries skipped, sorted case-insensitively; the home
    # directory is the tree root here, so the chain to pics/ is the one level under it
    home = str(tmp_path)
    roots = (home,)
    root = tmp_path / "pics"
    for folder in ["Zoo", "art", ".hidden"]:
        (root / folder).mkdir(parents=True)
    for name in ["b.PNG", "a.jpg", ".secret.png", "notes.txt", "clip.mp4"]:
        (root / name).write_bytes(b"")
    listing = browse_directory(str(root), roots, home)
    assert listing == DirectoryListing(str(root), home, ("art", "Zoo"), ("a.jpg", "b.PNG"), (TreeLevel(home, ("pics",)),))
    # a file path lists the directory holding it, so the dialog opens where the current value lives; tree=0 skips the chain
    assert browse_directory(str(root / "a.jpg"), roots, home) == listing
    assert browse_directory(str(root), roots, home, with_tree=False).ancestors == ()
    # every level keeps the directory on the chain, even a hidden one; a root itself has no chain
    (root / ".hidden" / "deep").mkdir()
    assert browse_directory(str(root / ".hidden" / "deep"), roots, home).ancestors == (
        TreeLevel(home, ("pics",)),
        TreeLevel(str(root), (".hidden", "art", "Zoo")),
        TreeLevel(str(root / ".hidden"), ("deep",)),
    )
    assert browse_directory(home, roots, home).ancestors == ()
    # restricted directories, the filesystem root and the parent of home, list no folders and show only the chain child
    assert browse_directory(str(tmp_path.parent), roots, home).dirs == ()
    outside = browse_directory(str(root), (str(tmp_path / "elsewhere"),), home)
    assert outside.ancestors[0].path == "/" and outside.ancestors[0].dirs == (tmp_path.parts[1],)
    assert outside.ancestors[-1] == TreeLevel(home, ("pics",))
    assert browse_directory("/", roots, home).parent is None
    with pytest.raises(FileNotFoundError):
        browse_directory(str(root / "nope"), roots, home)

    # tree roots: home first, then the mounted disks from the mount table, minus pseudo filesystems, the root and
    # system mounts, /home and the home directory itself, and autofs placeholders; octal escapes are decoded
    mounts = """\
/dev/nvme0n1p2 / ext4 rw 0 0
/dev/nvme0n1p1 /boot/efi vfat rw 0 0
/dev/loop3 /snap/core/1 squashfs ro 0 0
portal /run/user/1000/doc fuse.portal rw 0 0
/dev/sdb1 /media/ray/My\\040USB vfat rw 0 0
//nas/share /mnt/nas cifs rw 0 0
//nas/comfy /mnt/.comfyui cifs rw 0 0
auto.nas /mnt/auto autofs rw 0 0
/dev/sda1 /home ext4 rw 0 0
/dev/sda2 /home/ray ext4 rw 0 0
/dev/sda3 /runtime/data ext4 rw 0 0
"""
    assert mount_points(mounts, "/home/ray") == ("/media/ray/My USB", "/mnt/.comfyui", "/mnt/nas", "/runtime/data")
    assert tree_roots("/home/ray", mounts, [], [])[:3] == (
        TreeRoot("Home", "/home/ray"),
        TreeRoot("My USB", "/media/ray/My USB"),
        TreeRoot(".comfyui", "/mnt/.comfyui"),
    )
    assert tree_roots("/Users/ray", None, ["/Volumes/USB"], []) == (TreeRoot("Home", "/Users/ray"), TreeRoot("USB", "/Volumes/USB"))


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
