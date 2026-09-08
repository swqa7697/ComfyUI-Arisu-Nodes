#!/usr/bin/env bash
# Remove the venv plus everything clean.sh removes. Keeps uv.lock and pyproject.toml.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

log_info "removing .venv, then delegating to clean.sh for build outputs and caches..."

# .venv goes first, which is why clean.sh's './.venv/*' prune guards do not matter here.
rm -rf .venv
bash scripts/clean.sh

log_ok "done. uv.lock and pyproject.toml are kept."
