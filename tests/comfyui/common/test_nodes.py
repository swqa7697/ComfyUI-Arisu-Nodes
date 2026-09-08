"""Execute-level tests for the common nodes. Run via ``scripts/test-comfyui.sh``."""

from __future__ import annotations

import pytest
import torch

from src.arisu_nodes.common.nodes import ArisuExtractLastImages

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
