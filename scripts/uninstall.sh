#!/usr/bin/env bash
# Remove the venv plus everything clean.sh removes. Keeps uv.lock and pyproject.toml.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

log_info "removing .venv, then delegating to clean.sh for build outputs and caches..."

# clean.sh preserves the managed test infrastructure and developer artifacts.
rm -rf .venv
bash scripts/clean.sh

log_ok "done. uv.lock and pyproject.toml are kept."
