"""ComfyUI-dependent lane: needs ComfyUI's interpreter and source tree.

The whole directory is opt-in. When ``comfy_api`` is not importable (a bare
``uv run pytest`` in the project venv, or the PR gate) the test files are not
even collected, so nothing here can raise an ImportError. Run the lane via
``scripts/test-comfyui.sh``, which puts ComfyUI's root on ``sys.path`` through
``COMFYUI_PATH`` and runs pytest on ComfyUI's interpreter.

The lane has two execution contexts: the live install on a GPU machine, and the
throwaway ComfyUI clone with CPU-only torch that
``.github/workflows/comfyui-lane.yml`` builds. The second needs the CPU-mode
shim below; pytest runs it when it loads this conftest, before any test module
imports ``comfy.model_management``.
"""

from __future__ import annotations

import importlib.util

# fnmatch "*" spans "/", so the second pattern covers per-family subdirectories.
collect_ignore_glob = [] if importlib.util.find_spec("comfy_api") else ["test_*.py", "*/test_*.py"]

# Feature-gated imports (CLAUDE.md, Import conventions): this file must stay
# importable with neither ComfyUI nor torch installed.
if importlib.util.find_spec("comfy_api"):
    import comfy.cli_args
    import torch

    # ComfyUI reads CPU mode only from ``--cpu``, and ``comfy.options.args_parsing``
    # is False outside ``main.py``, so ``cli_args`` parses an empty argv and ``args.cpu``
    # stays False. Importing ``comfy.model_management`` then probes VRAM through
    # ``torch.cuda.current_device()`` and fails collection with "Torch not compiled with
    # CUDA enabled". There is no env var for it, so flip the parsed args in memory here,
    # before anything imports that module.
    if not torch.cuda.is_available():
        comfy.cli_args.args.cpu = True
