#!/bin/sh
set -eu
mkdir -p /opt/agent/bin
curl -fsSL https://x.ai/cli/install.sh -o /tmp/install-grok.sh
bash /tmp/install-grok.sh
cp -L /root/.grok/bin/grok /opt/agent/bin/grok
/opt/agent/bin/grok --version
