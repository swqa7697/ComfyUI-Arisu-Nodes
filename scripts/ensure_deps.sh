#!/usr/bin/env bash
# Make sure uv is on PATH; install it with the official installer if it is not.
# Writes only to ~/.local/bin (the installer's default), never into this repo.
set -euo pipefail

cd "$(dirname "$0")/.."
source scripts/logger.sh

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux | Darwin) ;;
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

if command -v uv > /dev/null 2>&1; then
    log_ok "uv already installed ($(uv --version) at $(command -v uv))"
    exit 0
fi

log_warn "uv not found; installing via the official installer..."
curl -LsSf https://astral.sh/uv/install.sh | sh

if ! command -v uv > /dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        log_warn "uv installed at $HOME/.local/bin/uv but not on PATH."
        log_warn "add this to your shell rc and restart:"
        log_warn "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        log_error "PATH not configured; re-run after sourcing your shell rc."
        exit 1
    fi
    log_error "uv install appears to have failed."
    exit 1
fi

log_ok "uv installed: $(uv --version)"
