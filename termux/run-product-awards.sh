#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
STATE_DIR="$PROJECT_DIR/state"
LOG="$STATE_DIR/product-awards.log"

mkdir -p "$STATE_DIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 524288 ]; then
    mv "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

cd "$PROJECT_DIR"
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [--force]" >&2
    exit 2
fi

COMMAND=product-awards
case "${1-}" in
    "")
        ;;
    --force)
        COMMAND=product-awards-force
        ;;
    *)
        echo "Usage: $0 [--force]" >&2
        exit 2
        ;;
esac

exec ./.venv/bin/python -m telegrambot "$COMMAND"
