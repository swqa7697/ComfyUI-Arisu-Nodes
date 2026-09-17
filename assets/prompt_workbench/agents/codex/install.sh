#!/bin/sh
set -eu
mkdir -p /opt/agent/bin
curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh
CODEX_NON_INTERACTIVE=1 CODEX_INSTALL_DIR=/opt/agent/bin CODEX_HOME=/opt/agent/codex-home \
    sh /tmp/install-codex.sh
/opt/agent/bin/codex --version
