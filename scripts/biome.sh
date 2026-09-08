#!/usr/bin/env bash
# Run the pinned Biome release through pnpm dlx: the one JS formatter and linter,
# configured in biome.json. No package.json, lockfile, or node_modules: pnpm keeps
# the binary in its own store, outside this repo. Keep biome.json's $schema URL on
# the same version when bumping. `make install` provides pnpm and node.
set -euo pipefail

cd "$(dirname "$0")/.."

BIOME_VERSION="2.5.12"

exec pnpm dlx "@biomejs/biome@$BIOME_VERSION" "$@"
