"""ComfyUI-Arisu-Nodes: the module ComfyUI imports for this node pack."""

from __future__ import annotations

from typing import List, Type

from comfy_api.latest import ComfyExtension, io

from .src.arisu_nodes.minimax_h3.nodes import NODES as MINIMAX_H3_NODES

__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]

WEB_DIRECTORY = "./web"


class ArisuNodesExtension(ComfyExtension):
    async def get_node_list(self) -> List[Type[io.ComfyNode]]:
        # One list per node family, in the order they appear in the docs.
        return [*MINIMAX_H3_NODES]


async def comfy_entrypoint() -> ArisuNodesExtension:
    return ArisuNodesExtension()
