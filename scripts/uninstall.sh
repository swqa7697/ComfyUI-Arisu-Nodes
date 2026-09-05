#!/usr/bin/env bash
# Remove the venv plus everything clean.sh removes. Keeps uv.lock and pyproject.toml.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

log_info "removing .venv, build outputs, and caches..."

rm -rf .venv dist build .ruff_cache .pytest_cache
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type d -name '*.egg-info' -prune -exec rm -rf {} +

log_ok "done. uv.lock and pyproject.toml are kept."
