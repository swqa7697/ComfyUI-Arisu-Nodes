#!/usr/bin/env bash
# Write-mode formatter chain behind `make tidy`. CI runs it and fails on any diff,
# so everything it rewrites must be committed in its normalized form.
set -euo pipefail

cd "$(dirname "$0")"
source scripts/logger.sh

log_info "ruff format"
uv run ruff format .

log_info "ruff check --fix"
uv run ruff check --fix .

log_info "uv-sort (pyproject.toml dependency lists)"
uv run uv-sort

log_info "beautysh (shell scripts, 4-space indent)"
uv run beautysh -i 4 scripts/*.sh tidy.sh

log_info "mbake (Makefile)"
uv run mbake format Makefile

log_info "biome (web/js and tests/web: format, lint fixes, import order)"
bash scripts/biome.sh check --write

log_ok "done"
