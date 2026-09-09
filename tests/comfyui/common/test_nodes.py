"""Execute-level tests for the common nodes. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

from pathlib import Path

import folder_paths
import numpy as np
import pytest
import torch
from PIL import Image

from src.arisu_nodes.common.nodes import ArisuExtractLastImages, ArisuLoadImage, ArisuPreviewSaveImage, ArisuPreviewSaveImageUpscale

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
