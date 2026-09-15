#!/bin/sh
# Run vendor installers only in the disposable Docker build stage.
set -eu

mkdir -p /opt/agent/bin
case "$1" in
    codex)
        curl -fsSL https://chatgpt.com/codex/install.sh -o /tmp/install-codex.sh
        CODEX_NON_INTERACTIVE=1 CODEX_INSTALL_DIR=/opt/agent/bin CODEX_HOME=/opt/agent/codex-home \
            sh /tmp/install-codex.sh
        ;;
    grok)
        curl -fsSL https://x.ai/cli/install.sh -o /tmp/install-grok.sh
        bash /tmp/install-grok.sh
        # Copy the installed binary, dereferencing the installer's download symlink.
        cp -L /root/.grok/bin/grok /opt/agent/bin/grok
        ;;
    *)
        echo "Unsupported agent: $1" >&2
        exit 1
        ;;
esac
"/opt/agent/bin/$1" --version
