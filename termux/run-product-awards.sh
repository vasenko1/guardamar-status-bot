#!/data/data/com.termux/files/usr/bin/sh

set -eu

MODE=${1:-publish}
case "$MODE" in
    discover)
        COMMAND=product-awards-discover
        ;;
    publish)
        COMMAND=product-awards
        ;;
    *)
        echo "ERROR: expected discover or publish" >&2
        exit 2
        ;;
esac

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

exec ./.venv/bin/python -m telegrambot "$COMMAND"
