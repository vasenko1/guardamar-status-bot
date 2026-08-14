#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
STATE_DIR="$PROJECT_DIR/state"
LOG="$STATE_DIR/transport.log"

mkdir -p "$STATE_DIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 524288 ]; then
    mv "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

cd "$PROJECT_DIR"
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

if ! command -v pdfinfo >/dev/null 2>&1 || ! command -v pdftoppm >/dev/null 2>&1; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Poppler is not installed"
    exit 1
fi

exec ./.venv/bin/python -m telegrambot sync-transport
