#!/usr/bin/env bash
# Remove caches and build outputs inside this checkout. Keeps .venv, uv.lock, and .tmp/.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

log_info "removing caches and build outputs (keeping .venv)..."

rm -rf dist build .ruff_cache .pytest_cache
find . -type d -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
find . -type d -name '*.egg-info' -not -path './.venv/*' -prune -exec rm -rf {} +

log_ok "done."
