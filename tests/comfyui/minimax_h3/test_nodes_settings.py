"""Execute-level tests for the video settings nodes and the hybrid nodes' settings input.

The settings nodes are plain arithmetic; the hybrid nodes run with stub CLIP
and VAEs so the override can be read off the latent geometry and the keyframe
latents. Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from src.arisu_nodes.minimax_h3.nodes import (
    ArisuMiniMaxH3HybridToVideo,
    ArisuMiniMaxH3HybridToVideoAdvanced,
    ArisuMiniMaxH3VideoSettings,
    ArisuMiniMaxH3VideoSettingsUpscale,
)
from tests.support.comfy import StubClip, StubVae, image

pytestmark = pytest.mark.comfyui


def _hybrid_kwargs() -> Dict[str, Any]:
    # widget values that disagree with every bundle used below
    return {
        "clip": StubClip(),
        "vae": StubVae(),
        "prompt": "a test",
        "width": 512,
        "height": 512,
        "length": 22,
        "ref_image_size": "match",
        "frame_picture_tags": "after_refs",
    }


def test_settings_nodes_derive_canvas_frames_and_upscale_targets():
    # the workflow's Resolution Configs + Duration Setter: 3:4 at 0.5 MP, x2, 5 s
    width, height, length, factor, target_width, target_height, bundle = ArisuMiniMaxH3VideoSettingsUpscale.execute(
        aspect_ratio="3:4 (Portrait Standard)", megapixels=0.5, upscale_factor=2.0, duration=5.0, advertise=True
    )
    assert (width, height, length) == (640, 832, 124)
    assert (factor, target_width, target_height) == (2.0, 1280, 1664)
    assert bundle == {"width": 640, "height": 832, "length": 124, "target_width": 1280, "target_height": 1664}

    # the plain variant carries no target; the duration snaps up to the 17k+5 grid
    width, height, length, bundle = ArisuMiniMaxH3VideoSettings.execute(
        aspect_ratio="16:9 (Widescreen)", megapixels=1.0, duration=10.0, advertise=False
    )
    assert (width, height, length) == (1376, 768, 243)
    assert bundle == {"width": 1376, "height": 768, "length": 243}

    # a fractional factor still lands the target on the 32 grid
    result = ArisuMiniMaxH3VideoSettingsUpscale.execute(
        aspect_ratio="16:9 (Widescreen)", megapixels=1.0, upscale_factor=1.25, duration=5.0, advertise=True
    )
    assert (result[4], result[5]) == (1728, 960)


def test_settings_bundle_overrides_the_hybrid_widgets_but_only_for_its_keys():
    upscale = ArisuMiniMaxH3VideoSettingsUpscale.execute("16:9 (Widescreen)", 1.0, 2.0, 5.0, True)[-1]
    plain = ArisuMiniMaxH3VideoSettings.execute("16:9 (Widescreen)", 1.0, 5.0, True)[-1]

    # the upscale bundle drives every size of the Advanced node: 1376 x 768 -> 86 x 48 latent, x2 for the target
    positive, latent, upscaled = ArisuMiniMaxH3HybridToVideoAdvanced.execute(
        target_width=256, target_height=256, settings=upscale, first_frame=image(768, 1376), **_hybrid_kwargs()
    )
    assert tuple(latent["samples"].tensors[0].shape) == (1, 24, 37, 48, 86)
    assert positive[0][1]["minimax_keyframes"][0]["latent"].shape == (1, 24, 1, 48, 86)
    assert upscaled[0][1]["minimax_keyframes"][0]["latent"].shape == (1, 24, 1, 96, 172)

    # a plain bundle leaves the Advanced node's target to its own widgets
    _positive, latent, upscaled = ArisuMiniMaxH3HybridToVideoAdvanced.execute(
        target_width=256, target_height=256, settings=plain, first_frame=image(768, 1376), **_hybrid_kwargs()
    )
    assert tuple(latent["samples"].tensors[0].shape) == (1, 24, 37, 48, 86)
    assert upscaled[0][1]["minimax_keyframes"][0]["latent"].shape == (1, 24, 1, 16, 16)

    # the plain node ignores the upscale bundle's target keys; without a bundle the widgets rule
    _positive, latent = ArisuMiniMaxH3HybridToVideo.execute(settings=upscale, **_hybrid_kwargs())
    assert tuple(latent["samples"].tensors[0].shape) == (1, 24, 37, 48, 86)
    _positive, latent = ArisuMiniMaxH3HybridToVideo.execute(**_hybrid_kwargs())
    assert tuple(latent["samples"].tensors[0].shape) == (1, 24, 7, 32, 32)
