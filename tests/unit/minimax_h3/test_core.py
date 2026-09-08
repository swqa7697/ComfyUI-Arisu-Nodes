"""Tests for the ComfyUI-free layer of the MiniMax H3 node family."""

from __future__ import annotations

from typing import List, Tuple

import pytest

from src.arisu_nodes.minimax_h3.core import (
    FRAME_TAG_MODES,
    REF_IMAGE_SIZE_MODES,
    adapt_canvas,
    align_clip_frames,
    align_frame_count,
    frame_needs_resize,
    keyframe_canvases,
    latent_size,
    order_picture_items,
    qwen_sample_indices,
    qwen_timestamps,
    ref_image_canvas,
    ref_video_canvas,
    resize_target,
    soundtrack_key,
    temporal_shape,
    validate_context_streams,
    video_frame_count,
    video_latent_t,
)


@pytest.mark.parametrize(("n", "expected"), [(5, 5), (22, 22), (6, 22), (124, 124), (125, 141)])
def test_align_frame_count_snaps_up_to_17k_plus_5(n: int, expected: int):
    assert align_frame_count(n) == expected


@pytest.mark.parametrize(("frame_count", "expected"), [(5, 2), (22, 7), (124, 37)])
def test_video_latent_t(frame_count: int, expected: int):
    assert video_latent_t(frame_count) == expected


def test_temporal_shape_default_length():
    assert temporal_shape(124) == (124, 37, 207)


def test_temporal_shape_clamps_short_lengths_to_five_frames():
    assert temporal_shape(1) == (5, 2, 8)


@pytest.mark.parametrize(("width", "height", "expected"), [(1920, 1080, (1344, 768)), (1080, 1920, (768, 1344)), (1024, 1024, (768, 768))])
def test_adapt_canvas(width: int, height: int, expected: Tuple[int, int]):
    assert adapt_canvas(width, height) == expected


def test_ref_image_canvas_match_scales_down_to_target_area():
    assert ref_image_canvas(4096, 2048, 1344, 768, "match") == (1440, 704)
    assert ref_image_canvas(4096, 2048, 2688, 1536, "match") == (2880, 1440)


def test_ref_image_canvas_never_upscales():
    assert ref_image_canvas(512, 256, 1344, 768, "match") == (512, 256)
    assert ref_image_canvas(512, 256, 1344, 768, "max") == (512, 256)


def test_ref_image_canvas_max_caps_short_edge():
    assert ref_image_canvas(5000, 3000, 1344, 768, "max") == (3424, 2048)


def test_ref_image_canvas_rejects_unknown_mode():
    with pytest.raises(ValueError, match="ref_image_size"):
        ref_image_canvas(512, 512, 1344, 768, "huge")
    assert "huge" not in REF_IMAGE_SIZE_MODES


def test_ref_video_canvas_uses_adapted_canvas_for_large_sources():
    assert ref_video_canvas(1920, 1080) == (1344, 768)


def test_ref_video_canvas_keeps_small_sources_small():
    assert ref_video_canvas(640, 360) == (640, 352)


@pytest.mark.parametrize(("n_frames", "frame_count", "expected"), [(200, 124, 124), (30, 124, 22), (5, 124, 5)])
def test_align_clip_frames(n_frames: int, frame_count: int, expected: int):
    assert align_clip_frames(n_frames, frame_count) == expected


def test_align_clip_frames_rejects_too_short_clips():
    with pytest.raises(ValueError, match="at least 5 frames"):
        align_clip_frames(4, 124)


def test_qwen_sampling_is_two_fps():
    assert qwen_sample_indices(22) == [0, 12]
    assert qwen_timestamps(2) == [0.0, 0.5]


def test_soundtrack_key_pairs_by_slot_index():
    assert soundtrack_key("ref_video_2") == "ref_video_audio_2"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("after_refs", ["r1", "r2", "f1"]), ("before_refs", ["f1", "r1", "r2"]), ("none", ["r1", "r2"])],
)
def test_order_picture_items(mode: str, expected: List[str]):
    assert mode in FRAME_TAG_MODES
    assert order_picture_items(mode, ["f1"], ["r1", "r2"]) == expected


def test_order_picture_items_rejects_unknown_mode():
    with pytest.raises(ValueError, match="frame_picture_tags"):
        order_picture_items("sometimes", ["f1"], ["r1"])


def test_latent_size_is_height_then_width():
    assert latent_size(1344, 768) == (48, 84)


def test_keyframe_canvases_lists_generation_canvas_first():
    assert keyframe_canvases(1344, 768, 2688, 1536) == [(1344, 768), (2688, 1536)]


def test_keyframe_canvases_collapses_equal_target():
    assert keyframe_canvases(1344, 768, 1344, 768) == [(1344, 768)]


@pytest.mark.parametrize(
    ("shape", "expected"),
    [((1, 768, 1344, 3), False), ((1, 768, 1344, 4), False), ((1, 768, 1024, 3), True), ((1, 1536, 1344, 3), True)],
)
def test_frame_needs_resize(shape: Tuple[int, ...], expected: bool):
    assert frame_needs_resize(shape, 1344, 768) is expected


@pytest.mark.parametrize(("latent_t", "expected"), [(2, 5), (7, 22), (37, 124)])
def test_video_frame_count_inverts_video_latent_t(latent_t: int, expected: int):
    assert video_frame_count(latent_t) == expected
    assert video_latent_t(expected) == latent_t


@pytest.mark.parametrize("latent_t", [0, 1, 3, 8])
def test_video_frame_count_rejects_off_grid_lengths(latent_t: int):
    with pytest.raises(ValueError, match="5k\\+2"):
        video_frame_count(latent_t)


def test_validate_context_streams_accepts_h3_av_layout():
    validate_context_streams((1, 24, 37, 48, 84), (1, 32, 2, 207))


@pytest.mark.parametrize(
    ("video_shape", "audio_shape", "match"),
    [
        ((1, 16, 37, 48, 84), (1, 32, 2, 207), "video latent"),
        ((24, 37, 48, 84), (1, 32, 2, 207), "video latent"),
        ((1, 24, 8, 48, 84), (1, 32, 2, 207), "5k\\+2"),
        ((1, 24, 37, 48, 84), (1, 32, 207), "audio latent"),
        ((1, 24, 37, 48, 84), (1, 32, 1, 207), "audio latent"),
    ],
)
def test_validate_context_streams_rejects_other_layouts(video_shape: Tuple[int, ...], audio_shape: Tuple[int, ...], match: str):
    with pytest.raises(ValueError, match=match):
        validate_context_streams(video_shape, audio_shape)


def test_resize_target_is_none_when_size_already_matches():
    assert resize_target((1, 24, 7, 48, 84), 1344, 768) is None


def test_resize_target_returns_latent_height_then_width():
    assert resize_target((1, 24, 7, 48, 84), 864, 480) == (30, 54)


@pytest.mark.parametrize(("width", "height"), [(1000, 768), (1344, 770)])
def test_resize_target_rejects_sizes_off_the_16_grid(width: int, height: int):
    with pytest.raises(ValueError, match="multiples of 16"):
        resize_target((1, 24, 7, 48, 84), width, height)
