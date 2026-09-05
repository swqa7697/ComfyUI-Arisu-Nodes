"""ComfyUI-Arisu-Nodes: the module ComfyUI imports for this node pack."""

from __future__ import annotations

from comfy_api.latest import ComfyExtension, io

from .src.arisu_nodes.nodes import ArisuExample

__all__ = ["comfy_entrypoint", "WEB_DIRECTORY"]

WEB_DIRECTORY = "./web"


class ArisuNodesExtension(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [ArisuExample]


async def comfy_entrypoint() -> ArisuNodesExtension:
    return ArisuNodesExtension()
