"""ComfyUI-Arisu-Nodes: the module ComfyUI imports for this node pack."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Type

import folder_paths
from comfy_api.latest import ComfyExtension, io
from server import PromptServer

from .src.arisu_nodes.common.nodes import NODES as COMMON_NODES
from .src.arisu_nodes.common.paths import initialize_roots
from .src.arisu_nodes.common.routes import register_routes
from .src.arisu_nodes.minimax_h3.nodes import NODES as MINIMAX_H3_NODES
from .src.arisu_nodes.minimax_h3.routes import register_routes as register_resource_routes

__all__ = ["WEB_DIRECTORY", "comfy_entrypoint"]

WEB_DIRECTORY = "./web"


class ArisuNodesExtension(ComfyExtension):
    """The V3 extension ComfyUI instantiates to discover this pack's nodes."""

    async def on_load(self) -> None:
        """Register the pack's HTTP routes on the running server.

        ComfyUI awaits this before ``PromptServer.add_routes()``, so the routes
        are also mirrored under ``/api``, where the frontend calls them. The
        ``instance`` attribute only exists once ComfyUI has built the server;
        the test lane imports the pack without one.
        """
        await asyncio.to_thread(initialize_roots, Path(folder_paths.get_system_user_directory("arisu_nodes")))
        server = getattr(PromptServer, "instance", None)
        if server is not None:
            register_routes(server.routes)
            register_resource_routes(server.routes, getattr(server, "app", None))

    async def get_node_list(self) -> List[Type[io.ComfyNode]]:
        """List every node class in the pack.

        Returns:
            The node classes, one family after another, in the order they appear
            in the docs.
        """
        return [*MINIMAX_H3_NODES, *COMMON_NODES]


async def comfy_entrypoint() -> ArisuNodesExtension:
    """Build the extension instance; ComfyUI calls this when loading the pack.

    Returns:
        The pack's ``ArisuNodesExtension``.
    """
    return ArisuNodesExtension()
