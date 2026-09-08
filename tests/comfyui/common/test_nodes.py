"""Execute-level tests for the common nodes. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

from pathlib import Path

import folder_paths
import pytest
import torch

from src.arisu_nodes.common.nodes import ArisuExtractLastImages, ArisuPreviewSaveImage, ArisuPreviewSaveImageUpscale

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
