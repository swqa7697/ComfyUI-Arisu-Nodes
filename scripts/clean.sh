#!/usr/bin/env bash
# Remove caches and build outputs inside this checkout. Keeps .venv, uv.lock, .misc/, and developer-managed .tmp/.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

log_info "removing caches and build outputs (keeping .venv)..."

rm -rf dist build .ruff_cache .pytest_cache
find . -type d \( -path './.venv' -o -path './.misc' -o -path './.tmp' \) -prune -o \
    -type d \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +

log_ok "done."
