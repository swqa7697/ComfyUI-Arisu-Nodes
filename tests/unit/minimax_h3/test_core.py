"""Tests for the ComfyUI-free layer of the MiniMax H3 node family.

The execute-level tests under ``tests/comfyui`` are the regression trunk; this
file keeps only the boundaries and branches they cannot reach (see CLAUDE.md,
Test growth rules).
"""

from __future__ import annotations

import pytest

from src.arisu_nodes.minimax_h3.core import (
    adapt_canvas,
    align_clip_frames,
    align_frame_count,
    canvas_from_megapixels,
    frames_for_duration,
    order_picture_items,
    ref_image_canvas,
    ref_video_canvas,
    scaled_canvas,
    temporal_shape,
    validate_context_streams,
    video_frame_count,
    video_latent_t,
)


def test_frame_grid_round_trips_between_pixels_and_latents():
    # (requested frames, aligned frames, latent frames): 17k+5 pixel frames <-> 5k+2 latent frames
    grid = [(5, 5, 2), (6, 22, 7), (22, 22, 7), (124, 124, 37), (125, 141, 42)]
    for requested, aligned, latent_t in grid:
        assert align_frame_count(requested) == aligned, f"case={requested!r}"
        assert video_latent_t(aligned) == latent_t, f"case={aligned!r}"
        assert video_frame_count(latent_t) == aligned, f"case={latent_t!r}"


def test_video_frame_count_rejects_off_grid_lengths():
    for latent_t in (0, 1, 3, 8):
        with pytest.raises(ValueError, match="5k\\+2") as excinfo:
            video_frame_count(latent_t)
        assert str(latent_t) in str(excinfo.value), f"case={latent_t!r}"


def test_temporal_shape_clamps_short_lengths_and_aligns_long_ones():
    assert temporal_shape(1) == (5, 2, 8)
    assert temporal_shape(124) == (124, 37, 207)
    assert temporal_shape(125) == (141, 42, 235)


def test_adapt_canvas_fits_landscape_portrait_and_square():
    cases = [((1920, 1080), (1344, 768)), ((1080, 1920), (768, 1344)), ((1024, 1024), (768, 768))]
    for (width, height), expected in cases:
        assert adapt_canvas(width, height) == expected, f"case={(width, height)!r}"


def test_ref_video_canvas_shrinks_to_source_but_never_beyond_the_canvas():
    assert ref_video_canvas(1920, 1080) == (1344, 768)
    assert ref_video_canvas(640, 360) == (640, 352)


def test_ref_image_canvas_never_upscales_and_max_caps_the_short_edge():
    for mode in ("match", "max"):
        assert ref_image_canvas(512, 256, 1344, 768, mode) == (512, 256), f"case={mode!r}"
    assert ref_image_canvas(5000, 3000, 1344, 768, "max") == (3424, 2048)


def test_unknown_modes_are_rejected_by_input_name():
    with pytest.raises(ValueError, match="ref_image_size"):
        ref_image_canvas(512, 512, 1344, 768, "huge")
    with pytest.raises(ValueError, match="frame_picture_tags"):
        order_picture_items("sometimes", ["f1"], ["r1"])


def test_align_clip_frames_crops_to_the_target_and_down_to_the_grid():
    cases = [((200, 124), 124), ((30, 124), 22), ((5, 124), 5)]
    for (n_frames, frame_count), expected in cases:
        assert align_clip_frames(n_frames, frame_count) == expected, f"case={(n_frames, frame_count)!r}"


def test_validate_context_streams_rejects_off_layout_pairs():
    cases = [
        ((1, 16, 37, 48, 84), (1, 32, 2, 207), "video latent"),
        ((24, 37, 48, 84), (1, 32, 2, 207), "video latent"),
        ((1, 24, 8, 48, 84), (1, 32, 2, 207), "5k\\+2"),
        ((1, 24, 37, 48, 84), (1, 32, 207), "audio latent"),
        ((1, 24, 37, 48, 84), (1, 32, 1, 207), "audio latent"),
    ]
    for video_shape, audio_shape, match in cases:
        with pytest.raises(ValueError, match=match):
            validate_context_streams(video_shape, audio_shape)


def test_settings_maths_snap_to_the_canvas_and_frame_grids():
    # (aspect ratio, megapixels) -> canvas; the core Resolution Selector's 1024^2 megapixel, rounded to 32
    canvases = [
        (("16:9 (Widescreen)", 1.0), (1376, 768)),
        (("3:4 (Portrait Standard)", 0.5), (640, 832)),
        (("1:1 (Square)", 0.1), (320, 320)),
        (("21:9 (Ultrawide)", 0.1), (480, 224)),
    ]
    for (aspect_ratio, megapixels), expected in canvases:
        assert canvas_from_megapixels(aspect_ratio, megapixels) == expected, f"case={(aspect_ratio, megapixels)!r}"
    with pytest.raises(ValueError, match="aspect_ratio"):
        canvas_from_megapixels("2:1", 1.0)

    # scaling rounds to 32 and never drops below one multiple
    assert scaled_canvas(640, 832, 2.0) == (1280, 1664)
    assert scaled_canvas(1376, 768, 1.25) == (1728, 960)
    assert scaled_canvas(64, 32, 0.25) == (32, 32)

    # (seconds, frames): 24 fps rounded, floored at 5, snapped up to 17k+5
    durations = [(0.1, 5), (0.2, 5), (5.0, 124), (5.2, 141), (10.0, 243)]
    for seconds, frames in durations:
        assert frames_for_duration(seconds) == frames, f"case={seconds!r}"
