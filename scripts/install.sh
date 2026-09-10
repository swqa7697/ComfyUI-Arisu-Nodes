#!/usr/bin/env bash
# Create the project venv with the dev group, after ensure_deps.sh has provided uv,
# pnpm, and node. LOCKED=1 adds --locked (what CI uses) so a stale uv.lock fails
# instead of being silently re-resolved.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

bash scripts/ensure_deps.sh

if [[ "${LOCKED:-0}" == "1" ]]; then
    log_info "syncing dev dependencies from uv.lock (--locked)..."
    uv sync --locked --all-groups
else
    log_info "syncing dev dependencies..."
    uv sync --all-groups
fi

log_ok "done. virtualenv at $(pwd)/.venv"
