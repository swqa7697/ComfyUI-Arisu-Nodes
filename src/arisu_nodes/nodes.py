"""V3 node definitions.

Importing this module requires ComfyUI's source tree and virtual environment
(``comfy_api`` pulls in torch). Keep ComfyUI-free logic in ``core.py``.
"""

from __future__ import annotations

import logging

import torch
from comfy_api.latest import io

from .core import PRINT_MODES, describe_inputs, invert

logger = logging.getLogger(__name__)


class ArisuExample(io.ComfyNode):
    """Placeholder node carried over from the scaffold: inverts an image."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="ArisuExample",
            display_name="Arisu Example",
            category="Arisu",
            description="Inverts the input image. Placeholder node from the project scaffold.",
            inputs=[
                io.Image.Input("image", tooltip="Image batch to invert."),
                io.Int.Input("int_field", default=0, min=0, max=4096, step=64, tooltip="An integer parameter."),
                io.Float.Input("float_field", default=1.0, min=0.0, max=10.0, step=0.01, round=0.001, tooltip="A float parameter."),
                io.Combo.Input(
                    "print_to_screen",
                    options=list(PRINT_MODES),
                    default="enable",
                    tooltip="Log the widget values to the server console.",
                ),
                io.String.Input("string_field", default="Hello World!", tooltip="A text parameter."),
            ],
            outputs=[io.Image.Output("image", tooltip="The inverted image.")],
        )

    @classmethod
    def execute(
        cls,
        image: torch.Tensor,
        int_field: int,
        float_field: float,
        print_to_screen: str,
        string_field: str,
    ) -> io.NodeOutput:
        if print_to_screen == "enable":
            logger.info(describe_inputs(string_field, int_field, float_field))
        return io.NodeOutput(invert(image))
