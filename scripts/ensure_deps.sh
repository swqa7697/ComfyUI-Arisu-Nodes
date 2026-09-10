#!/usr/bin/env bash
# Make sure uv, pnpm, and node are on PATH; install any that are missing with their
# official installers. Writes only under $HOME (~/.local/bin, $PNPM_HOME), never into
# this repo. pnpm is installed standalone so it can also provide node (`pnpm env`);
# npm is never used.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux) PNPM_HOME="${PNPM_HOME:-$HOME/.local/share/pnpm}" ;;
    Darwin) PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}" ;;
    *)
        log_error "unsupported OS: $OS (Linux or macOS only)"
        exit 1
        ;;
esac

case "$ARCH" in
    x86_64 | amd64 | aarch64 | arm64) ;;
    *)
        log_error "unsupported architecture: $ARCH"
        exit 1
        ;;
esac

# The installer put $1 at $2, but the shell cannot see it yet: print the rc line $3 and stop.
path_hint() {
    log_warn "$1 installed at $2 but not on PATH."
    log_warn "add this to your shell rc and restart:"
    log_warn "    $3"
    log_error "PATH not configured; re-run after sourcing your shell rc."
    exit 1
}

PNPM_PATH_LINE="export PNPM_HOME=\"$PNPM_HOME\"; export PATH=\"\$PNPM_HOME:\$PATH\""

if command -v uv > /dev/null 2>&1; then
    log_ok "uv already installed ($(uv --version) at $(command -v uv))"
else
    log_warn "uv not found; installing via the official installer..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    if ! command -v uv > /dev/null 2>&1; then
        [ -x "$HOME/.local/bin/uv" ] && path_hint uv "$HOME/.local/bin/uv" 'export PATH="$HOME/.local/bin:$PATH"'
        log_error "uv install appears to have failed."
        exit 1
    fi
    log_ok "uv installed: $(uv --version)"
fi

if command -v pnpm > /dev/null 2>&1; then
    log_ok "pnpm already installed ($(pnpm --version) at $(command -v pnpm))"
else
    log_warn "pnpm not found; installing via the official installer..."
    curl -fsSL https://get.pnpm.io/install.sh | sh -
    if ! command -v pnpm > /dev/null 2>&1; then
        [ -x "$PNPM_HOME/pnpm" ] && path_hint pnpm "$PNPM_HOME/pnpm" "$PNPM_PATH_LINE"
        log_error "pnpm install appears to have failed."
        exit 1
    fi
    log_ok "pnpm installed: $(pnpm --version)"
fi

# The web lane's resolve hook needs module.registerHooks (Node >= 22.15): a feature
# probe, so a node too old for it counts as missing.
node_ok() {
    command -v node > /dev/null 2>&1 &&
    node -e 'process.exit(typeof require("node:module").registerHooks === "function" ? 0 : 1)'
}

if node_ok; then
    log_ok "node already installed ($(node --version) at $(command -v node))"
else
    log_warn "node missing or older than 22.15; installing Node 24 via pnpm env..."
    pnpm env use --global 24
    if ! node_ok; then
        [ -x "$PNPM_HOME/node" ] && path_hint node "$PNPM_HOME/node" "$PNPM_PATH_LINE"
        log_error "node install appears to have failed."
        exit 1
    fi
    log_ok "node installed: $(node --version)"
fi
