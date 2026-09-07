"""ComfyUI-dependent lane: needs ComfyUI's interpreter and source tree.

The whole directory is opt-in. When ``comfy_api`` is not importable (a bare
``uv run pytest`` in the project venv, or CI) the test files are not even
collected, so nothing here can raise an ImportError. Run the lane via
``scripts/test-comfyui.sh``, which puts ComfyUI's root on ``sys.path`` through
``COMFYUI_PATH`` and runs pytest on ComfyUI's interpreter.
"""

import importlib.util

# fnmatch "*" spans "/", so the second pattern covers per-family subdirectories.
collect_ignore_glob = [] if importlib.util.find_spec("comfy_api") else ["test_*.py", "*/test_*.py"]
