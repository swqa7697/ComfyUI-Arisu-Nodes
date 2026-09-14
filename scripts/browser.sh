#!/usr/bin/env bash
# Browser tooling is isolated from both the normal dev environment and ComfyUI.
set -euo pipefail
cd "$(dirname "$0")/.."
BROWSER_ENV="$PWD/.tmp/browser/env"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.tmp/browser/binaries"
export ARISU_BROWSER_TEST=1
unset COMFYUI_PATH
case "${1:-test}" in
    install)
        uv venv --allow-existing "$BROWSER_ENV"
        uv pip install --python "$BROWSER_ENV/bin/python" --group "$PWD/pyproject.toml:browser"
        uv pip install --python "$BROWSER_ENV/bin/python" --upgrade --prerelease disallow comfyui-frontend-package
        "$BROWSER_ENV/bin/python" -m playwright install chromium
        ;;
    test|inspect)
        if [[ ! -x "$BROWSER_ENV/bin/python" ]] || ! "$BROWSER_ENV/bin/python" -c 'import aiohttp, PIL, playwright, pytest, comfyui_frontend_package' 2>/dev/null; then
            echo "Browser setup missing. Run make browser-install." >&2
            exit 1
        fi
        BROWSER_MODE="${1:-test}"
        if [[ $# -gt 0 ]]; then
            shift
        fi
        if [[ "$BROWSER_MODE" == "test" ]]; then
            exec "$BROWSER_ENV/bin/python" -m pytest -m browser tests/browser "$@"
        fi
        exec "$BROWSER_ENV/bin/python" -m tests.browser.support.harness "$@"
        ;;
    *) echo "Usage: scripts/browser.sh install|test|inspect" >&2; exit 2 ;;
esac
