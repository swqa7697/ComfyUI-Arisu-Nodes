"""Tests for the ComfyUI-free layer of the common node family."""

from __future__ import annotations

from src.arisu_nodes.common.core import join_path


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
