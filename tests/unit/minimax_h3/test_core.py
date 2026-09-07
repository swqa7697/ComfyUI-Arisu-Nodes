"""Tests for the ComfyUI-free layer of the MiniMax H3 node family."""

import pytest

from src.arisu_nodes.minimax_h3.core import (
    FRAME_TAG_MODES,
    REF_IMAGE_SIZE_MODES,
    adapt_canvas,
    align_clip_frames,
    align_frame_count,
    latent_size,
    order_picture_items,
    qwen_sample_indices,
    qwen_timestamps,
    ref_image_canvas,
    ref_video_canvas,
    soundtrack_key,
    temporal_shape,
    video_latent_t,
)


@pytest.mark.parametrize(("n", "expected"), [(5, 5), (22, 22), (6, 22), (124, 124), (125, 141)])
def test_align_frame_count_snaps_up_to_17k_plus_5(n, expected):
    assert align_frame_count(n) == expected


@pytest.mark.parametrize(("frame_count", "expected"), [(5, 2), (22, 7), (124, 37)])
def test_video_latent_t(frame_count, expected):
    assert video_latent_t(frame_count) == expected


def test_temporal_shape_default_length():
    assert temporal_shape(124) == (124, 37, 207)


def test_temporal_shape_clamps_short_lengths_to_five_frames():
    assert temporal_shape(1) == (5, 2, 8)


@pytest.mark.parametrize(("width", "height", "expected"), [(1920, 1080, (1344, 768)), (1080, 1920, (768, 1344)), (1024, 1024, (768, 768))])
def test_adapt_canvas(width, height, expected):
    assert adapt_canvas(width, height) == expected


def test_ref_image_canvas_match_scales_down_to_target_area():
    assert ref_image_canvas(4096, 2048, 1344, 768, "match") == (1440, 704)


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
def test_align_clip_frames(n_frames, frame_count, expected):
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
def test_order_picture_items(mode, expected):
    assert mode in FRAME_TAG_MODES
    assert order_picture_items(mode, ["f1"], ["r1", "r2"]) == expected


def test_order_picture_items_rejects_unknown_mode():
    with pytest.raises(ValueError, match="frame_picture_tags"):
        order_picture_items("sometimes", ["f1"], ["r1"])


def test_latent_size_is_height_then_width():
    assert latent_size(1344, 768) == (48, 84)
