"""ComfyUI-free logic for arisu_nodes.

Everything here must import only the standard library so it can be unit-tested
in the project's own environment, without torch or ComfyUI on the path.
"""

from __future__ import annotations

from typing import Any

PRINT_MODES = ("enable", "disable")


def describe_inputs(string_field: str, int_field: int, float_field: float) -> str:
    """Format the widget values of the example node for logging.

    Args:
        string_field: The text widget value.
        int_field: The integer widget value.
        float_field: The float widget value.

    Returns:
        A multi-line, human-readable summary of the three values.
    """
    return "\n".join(
        (
            "Your input contains:",
            f"    string_field aka input text: {string_field}",
            f"    int_field: {int_field}",
            f"    float_field: {float_field}",
        )
    )


def invert(image: Any) -> Any:
    """Invert values in the 0.0-1.0 range.

    Works on any object supporting ``float - x`` (a torch tensor, a numpy
    array, or a plain float), so it stays importable without torch.

    Args:
        image: Values in the 0.0-1.0 range.

    Returns:
        ``1.0 - image``, with the same type as the input.
    """
    return 1.0 - image
