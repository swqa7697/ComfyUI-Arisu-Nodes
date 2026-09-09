"""Execute-level tests for the common nodes. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

from pathlib import Path

import folder_paths
import numpy as np
import pytest
import torch
from PIL import Image

from src.arisu_nodes.common.nodes import (
    ArisuExtractLastImages,
    ArisuLoadImage,
    ArisuPreviewSaveImage,
    ArisuPreviewSaveImageUpscale,
    ArisuResizeImage,
)

pytestmark = pytest.mark.comfyui


def test_extract_last_images_keeps_the_tail_and_caps_at_the_batch():
    batch = torch.rand(5, 8, 8, 3)

    out = ArisuExtractLastImages.execute(images=batch, count=2)[0]
    assert torch.equal(out, batch[3:])
    # a copy, so editing the result cannot bleed into the source batch
    out[0, 0, 0, 0] = 2.0
    assert batch[3, 0, 0, 0] != 2.0

    assert torch.equal(ArisuExtractLastImages.execute(images=batch, count=1)[0], batch[4:])
    assert torch.equal(ArisuExtractLastImages.execute(images=batch, count=10)[0], batch)


def test_preview_save_nodes_pass_through_and_only_write_the_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(folder_paths, "temp_directory", str(tmp_path / "temp"))
    monkeypatch.setattr(folder_paths, "output_directory", str(tmp_path / "output"))
    batch = torch.rand(2, 8, 8, 3)

    out = ArisuPreviewSaveImage.execute(images=batch, path="shots/a")
    # the passthrough is the very same tensor: no copy, no save-time upscale leaking into the graph
    assert out.args[0] is batch
    # a plain dict, not a UIOutput: the run's widget values ride along with the previews
    assert isinstance(out.ui, dict)
    previews = out.ui["images"]
    assert [p["type"] for p in previews] == ["temp", "temp"]
    assert all((tmp_path / "temp" / p["subfolder"] / p["filename"]).is_file() for p in previews)
    # the run records the widget value for a linked path input and writes nothing under output/
    assert out.ui["path"] == ["shots/a"]
    assert not (tmp_path / "output").exists()

    out = ArisuPreviewSaveImageUpscale.execute(images=batch, path="shots/a", upscale_model="none")
    assert out.args[0] is batch
    assert isinstance(out.ui, dict)
    assert out.ui["upscale_model"] == ["none"]
    assert len(out.ui["images"]) == 2
    assert not (tmp_path / "output").exists()


def test_load_image_decodes_like_the_stock_loader(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(folder_paths, "input_directory", str(tmp_path / "input"))
    (tmp_path / "input" / "sub").mkdir(parents=True)
    rgba = np.zeros((4, 6, 4), dtype=np.uint8)
    rgba[..., 0] = 255
    rgba[..., 3] = 51
    Image.fromarray(rgba, "RGBA").save(tmp_path / "input" / "sub" / "a.png")
    Image.fromarray(np.full((3, 5, 3), 128, dtype=np.uint8)).save(tmp_path / "elsewhere.jpg")
    frames = [Image.fromarray(np.full((2, 2, 3), value, dtype=np.uint8)) for value in (0, 255)]
    frames[0].save(tmp_path / "anim.gif", save_all=True, append_images=frames[1:])

    # a path relative to the input directory: RGB pixels, the alpha channel dropped; the image is the one output
    (image,) = ArisuLoadImage.execute(path="sub/a.png").args
    assert image.shape == (1, 4, 6, 3)
    assert torch.allclose(image[0, 0, 0], torch.tensor([1.0, 0.0, 0.0]))
    # an absolute path outside the input directory
    (image,) = ArisuLoadImage.execute(path=str(tmp_path / "elsewhere.jpg")).args
    assert image.shape == (1, 3, 5, 3)
    # every frame of an animation is one image of the batch
    (image,) = ArisuLoadImage.execute(path=str(tmp_path / "anim.gif")).args
    assert image.shape == (2, 2, 2, 3)
    # a crop, left,top,width,height in pixels, is cut from every frame after decoding, never resized: the whole image
    # is no crop, a box past the edge is cut to the image, and one outside it is an error
    (image,) = ArisuLoadImage.execute(path="sub/a.png", crop="1,1,3,2").args
    assert image.shape == (1, 2, 3, 3)
    (image,) = ArisuLoadImage.execute(path="sub/a.png", crop="0,0,6,4").args
    assert image.shape == (1, 4, 6, 3)
    (image,) = ArisuLoadImage.execute(path="sub/a.png", crop="4,2,10,10").args
    assert image.shape == (1, 2, 2, 3)
    (image,) = ArisuLoadImage.execute(path=str(tmp_path / "anim.gif"), crop="0,0,1,1").args
    assert image.shape == (2, 1, 1, 3)
    with pytest.raises(ValueError):
        ArisuLoadImage.execute(path="sub/a.png", crop="6,0,1,1")

    # validation before the run: a linked input passes; blank, missing and non-image paths are refused by name,
    # and so is a malformed crop
    assert ArisuLoadImage.validate_inputs() is True
    assert ArisuLoadImage.validate_inputs(path="sub/a.png", crop="") is True
    for bad_crop in ["1,2,3", "0,0,0,5"]:
        assert isinstance(ArisuLoadImage.validate_inputs(path="sub/a.png", crop=bad_crop), str), f"case={bad_crop!r}"
    (tmp_path / "notes.txt").write_text("x")
    for bad in ["", "sub/missing.png", str(tmp_path / "notes.txt")]:
        assert isinstance(ArisuLoadImage.validate_inputs(path=bad), str), f"case={bad!r}"
    # the cache key follows the file on disk
    assert ArisuLoadImage.fingerprint_inputs() is None
    before = ArisuLoadImage.fingerprint_inputs(path="sub/a.png")
    Image.fromarray(rgba[:, :3], "RGBA").save(tmp_path / "input" / "sub" / "a.png")
    assert ArisuLoadImage.fingerprint_inputs(path="sub/a.png") != before


def test_resize_image_scales_pads_crops_and_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(folder_paths, "temp_directory", str(tmp_path / "temp"))
    image = torch.rand(2, 40, 60, 3)
    base = {
        "resize_method": "bilinear",
        "mode": "stretch",
        "pad_color": "0, 0, 0",
        "crop_position": "center",
        "divisible_by": 2,
    }

    # stretch: exactly the requested size; without a mask input the mask output is ComfyUI's empty 64x64 placeholder, as is
    # a 64x64 placeholder fed in; the result is previewed as temp PNGs, one per image
    out = ArisuResizeImage.execute(image=image, width=30, height=30, **base)
    resized, mask = out.args
    assert resized.shape == (2, 30, 30, 3)
    assert mask.shape == (1, 64, 64) and not mask.any()
    assert ArisuResizeImage.execute(image=image, mask=torch.zeros(1, 64, 64), width=30, height=30, **base).args[1].shape == (1, 64, 64)
    previews = out.ui.as_dict()["images"]
    assert [p["type"] for p in previews] == ["temp", "temp"]
    assert all((tmp_path / "temp" / p["subfolder"] / p["filename"]).is_file() for p in previews)
    # a zero side comes from the image: fitted at the aspect ratio here
    assert ArisuResizeImage.execute(image=image, width=0, height=20, **{**base, "mode": "resize"}).args[0].shape == (
        2,
        20,
        30,
        3,
    )

    # pad: the canvas is the request snapped to the grid (96x48), the image fitted inside it (72x48) and anchored left, the
    # rest the colour; the mask is 1 over the padding and 0 under the image, batch-sized without a mask input
    settings = {**base, "mode": "pad", "pad_color": "#ff0000", "crop_position": "left", "divisible_by": 16}
    padded, mask = ArisuResizeImage.execute(image=image, width=100, height=50, **settings).args
    assert padded.shape == (2, 48, 96, 3) and mask.shape == (2, 48, 96)
    assert torch.allclose(padded[:, :, 72:], torch.tensor([1.0, 0.0, 0.0]))
    assert mask[:, :, 72:].eq(1).all() and mask[:, :, :72].eq(0).all()
    # a colour name goes through Pillow; a mask of another size is fitted to the image first and keeps its own batch
    padded, mask = ArisuResizeImage.execute(
        image=image, mask=torch.ones(1, 10, 15), width=100, height=50, **{**settings, "pad_color": "white"}
    ).args
    assert torch.allclose(padded[:, :, 72:], torch.tensor([1.0, 1.0, 1.0]))
    assert mask.shape == (1, 48, 96) and mask.eq(1).all()

    # crop: the source is cut to the target's aspect ratio at the anchor before scaling, and a given mask takes the same cut;
    # the right 40 of 60 columns are marked, so the right-anchored cut keeps only marked pixels and the left-anchored one
    # keeps 20 unmarked columns, half the cut, hence half the output
    marked = torch.zeros(2, 40, 60)
    marked[:, :, 20:] = 1.0
    settings = {**base, "mode": "crop", "resize_method": "nearest-exact"}
    cropped, mask = ArisuResizeImage.execute(image=image, mask=marked, width=20, height=20, **{**settings, "crop_position": "right"}).args
    assert cropped.shape == (2, 20, 20, 3) and mask.eq(1).all()
    _, mask = ArisuResizeImage.execute(image=image, mask=marked, width=20, height=20, **{**settings, "crop_position": "left"}).args
    assert mask[:, :, :10].eq(0).all() and mask[:, :, 10:].eq(1).all()

    # validation before the run: linked inputs pass; an unfillable pad colour is refused, only when the pad mode would use it
    assert ArisuResizeImage.validate_inputs() is True
    assert ArisuResizeImage.validate_inputs(mode="stretch", pad_color="white") is True
    assert isinstance(ArisuResizeImage.validate_inputs(mode="pad", pad_color="no such colour"), str)
    assert isinstance(ArisuResizeImage.validate_inputs(pad_color="1, 2"), str)
    assert ArisuResizeImage.validate_inputs(mode="stretch", pad_color="no such colour") is True

    # a bypassed node passes each output through the input at the same slot when the types match, else the first input of
    # its type: image is the first input and output, mask the only MASK input and the second output
    schema = ArisuResizeImage.GET_SCHEMA()
    assert (schema.inputs[0].id, schema.inputs[0].io_type) == ("image", "IMAGE")
    assert [i.id for i in schema.inputs if i.io_type == "MASK"] == ["mask"]
    assert [(o.id, o.io_type) for o in schema.outputs] == [("image", "IMAGE"), ("mask", "MASK")]
