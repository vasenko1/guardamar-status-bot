#!/data/data/com.termux/files/usr/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

LOG="$PROJECT_DIR/state/pharmacy.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

exec >>"$LOG" 2>&1
exec ./.venv/bin/python -m telegrambot sync-pharmacy
