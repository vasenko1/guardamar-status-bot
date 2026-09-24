#!/data/data/com.termux/files/usr/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

LOG="$PROJECT_DIR/state/daily.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

exec >>"$LOG" 2>&1

./.venv/bin/python -m telegrambot morning
MORNING_STATUS=$?

./.venv/bin/python -m telegrambot suma
SUMA_STATUS=$?
if [ "$SUMA_STATUS" -ne 0 ]; then
    echo "SUMA one-shot failed with status $SUMA_STATUS"
fi

exit "$MORNING_STATUS"
