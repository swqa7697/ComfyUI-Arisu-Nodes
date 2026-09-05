# Shared logging helpers for scripts/*.sh and tidy.sh. Source it after cd-ing to
# the repo root; never execute it.
#   source scripts/logger.sh
# Modeled on worldengine/seer/scripts/logger.sh: TTY-gated colors and
# "<script> | <timestamp> | <mark> <message>" lines.

filename=$(basename "$0" .sh)

# Colors, gated on a TTY so CI logs and pipes stay free of escape codes.
if [ -t 1 ]; then
    C_RED='\033[0;31m'
    C_GREEN='\033[0;32m'
    C_YELLOW='\033[0;33m'
    C_BLUE='\033[0;34m'
    C_DIM='\033[2m'
    C_RESET='\033[0m'
else
    C_RED='' C_GREEN='' C_YELLOW='' C_BLUE='' C_DIM='' C_RESET=''
fi

# printf %b so the color escapes render; the script name and time stay dim.
_log_line() {
    printf "${C_DIM}%s | %s |${C_RESET} %b\n" \
        "$filename" "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

log_info() { _log_line "${C_BLUE}•${C_RESET} $1"; }
log_ok() { _log_line "${C_GREEN}✓${C_RESET} $1"; }
log_warn() { _log_line "${C_YELLOW}!${C_RESET} $1" >&2; }
log_error() { _log_line "${C_RED}✗${C_RESET} $1" >&2; }
