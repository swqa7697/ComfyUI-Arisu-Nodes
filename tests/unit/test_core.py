"""Tests for the ComfyUI-free layer of arisu_nodes."""

import pytest

from src.arisu_nodes.core import describe_inputs, invert


def test_describe_inputs_lists_every_field():
    text = describe_inputs("hello", 64, 0.5)
    assert text.splitlines() == [
        "Your input contains:",
        "    string_field aka input text: hello",
        "    int_field: 64",
        "    float_field: 0.5",
    ]


@pytest.mark.parametrize(("value", "expected"), [(0.0, 1.0), (1.0, 0.0), (0.25, 0.75)])
def test_invert_scalar(value, expected):
    assert invert(value) == pytest.approx(expected)


def test_invert_is_its_own_inverse():
    assert invert(invert(0.3)) == pytest.approx(0.3)
