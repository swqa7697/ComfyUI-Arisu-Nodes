#!/usr/bin/env bash
# Run the ComfyUI-dependent test lane (tests/comfyui) on ComfyUI's interpreter.
# Reads ComfyUI's venv and source tree; writes nothing to either.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

# make exports COMFYUI_PATH into this script (see the Makefile's hard-boundary
# block); this default only covers running the script directly.
COMFYUI_PATH="${COMFYUI_PATH:-$HOME/apps/comfyui}"
COMFY_PY="$COMFYUI_PATH/.venv/bin/python"

if [[ ! -x "$COMFY_PY" ]]; then
    log_error "no interpreter at $COMFY_PY"
    log_warn "set COMFYUI_PATH to your ComfyUI root; 'make comfyui-path' shows the current value"
    exit 1
fi

# COMFYUI_PATH: tests/conftest.py puts it on sys.path so comfy_api resolves.
# PYTHONDONTWRITEBYTECODE: importing ComfyUI's modules must not leave
# __pycache__ files behind under the ComfyUI install.
export COMFYUI_PATH PYTHONDONTWRITEBYTECODE=1

# --no-project: leave this project's .venv alone. --python plus --with layer an
# ephemeral pytest on top of ComfyUI's site-packages without installing into it.
exec uv run --no-project --python "$COMFY_PY" --with pytest pytest -m comfyui "$@"
