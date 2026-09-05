"""Regression flow: the pack loads and runs the way ComfyUI loads and runs it.

Nothing else verifies that the node pack imports until a clone is dropped into
a live ComfyUI and the service restarted, so this lane is the early warning.
Run via ``scripts/test-comfyui.sh``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from types import ModuleType

import pytest
import torch
from comfy_api.latest import ComfyExtension

from src.arisu_nodes.nodes import ArisuExample

pytestmark = pytest.mark.comfyui

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pack() -> ModuleType:
    """Import the repo root as a package exactly like ComfyUI's ``load_custom_node``.

    ComfyUI never puts the pack on ``sys.path``; it builds a spec from the
    directory's ``__init__.py`` under a module name derived from the path, so
    the entry file's relative imports (``from .src... import``) must work that
    way.
    """
    name = str(REPO_ROOT).replace(".", "_x_")
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "__init__.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_pack_loads_like_comfyui(pack: ModuleType):
    extension = asyncio.run(pack.comfy_entrypoint())
    assert isinstance(extension, ComfyExtension)

    nodes = asyncio.run(extension.get_node_list())
    # GET_SCHEMA is what ComfyUI calls at startup: it checks that define_schema
    # and execute are overridden and that input/output ids are unique.
    schemas = [node.GET_SCHEMA() for node in nodes]
    assert [schema.node_id for schema in schemas] == ["ArisuExample"]

    # V3 passes inputs to execute as keyword arguments named by input id, so a
    # mismatch only surfaces as a TypeError once a workflow runs.
    for node, schema in zip(nodes, schemas):
        assert {i.id for i in schema.inputs} == set(inspect.signature(node.execute).parameters), schema.node_id

    # The loader resolves WEB_DIRECTORY relative to the pack and silently skips
    # a missing directory.
    assert (REPO_ROOT / pack.WEB_DIRECTORY).is_dir()


def test_execute_inverts_and_logs(caplog: pytest.LogCaptureFixture):
    image = torch.full((1, 4, 4, 3), 0.25)
    kwargs = {"image": image, "int_field": 0, "float_field": 1.0, "string_field": "hello"}

    with caplog.at_level(logging.INFO):
        result = ArisuExample.execute(print_to_screen="enable", **kwargs)
    assert result.result is not None
    (output,) = result.result
    assert torch.equal(output, 1.0 - image)
    assert "string_field aka input text: hello" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.INFO):
        ArisuExample.execute(print_to_screen="disable", **kwargs)
    assert "Your input contains" not in caplog.text
