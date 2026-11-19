#!/usr/bin/env bash
# pnpm dlx runs Biome from its own store without a local package.json.
set -euo pipefail

cd "$(dirname "$0")/.."

exec pnpm dlx @biomejs/biome "$@"
