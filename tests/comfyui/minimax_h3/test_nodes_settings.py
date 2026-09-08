"""Execute-level tests for the video settings nodes.

The settings nodes are plain arithmetic on MiniMax H3's canvas and frame
grids; the hybrid nodes take their values through ordinary INT links or the
frontend's advertising, so nothing here runs them. Run via
``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import pytest

from src.arisu_nodes.minimax_h3.nodes import ArisuMiniMaxH3VideoSettings, ArisuMiniMaxH3VideoSettingsUpscale

pytestmark = pytest.mark.comfyui


def test_settings_nodes_derive_canvas_frames_and_upscale_targets():
    # the workflow's Resolution Configs + Duration Setter: 3:4 at 0.5 MP, x2, 5 s
    width, height, length, factor, target_width, target_height = ArisuMiniMaxH3VideoSettingsUpscale.execute(
        aspect_ratio="3:4 (Portrait Standard)", megapixels=0.5, upscale_factor=2.0, duration=5.0, advertise=True
    )
    assert (width, height, length) == (640, 832, 124)
    assert (factor, target_width, target_height) == (2.0, 1280, 1664)

    # the plain variant carries no target; the duration snaps up to the 17k+5 grid
    width, height, length = ArisuMiniMaxH3VideoSettings.execute(
        aspect_ratio="16:9 (Widescreen)", megapixels=1.0, duration=10.0, advertise=False
    )
    assert (width, height, length) == (1376, 768, 243)

    # a fractional factor still lands the target on the 32 grid
    result = ArisuMiniMaxH3VideoSettingsUpscale.execute(
        aspect_ratio="16:9 (Widescreen)", megapixels=1.0, upscale_factor=1.25, duration=5.0, advertise=True
    )
    assert (result[4], result[5]) == (1728, 960)
