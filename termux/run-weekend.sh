#!/data/data/com.termux/files/usr/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MODE=${1-}

case "$MODE" in
    ""|--fresh) ;;
    *)
        echo "Usage: run-weekend.sh [--fresh]" >&2
        exit 2
        ;;
esac

cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

LOG="$PROJECT_DIR/state/weekend.log"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

exec >>"$LOG" 2>&1

if [ "$MODE" = "--fresh" ]; then
    if ! "$SCRIPT_DIR/sync-municipal-events.sh"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING municipal event refresh failed; using last-good state"
    fi
    if ! "$SCRIPT_DIR/sync-agenda-events.sh"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING Agenda Guardamar refresh failed; using last-good state"
    fi
fi

exec ./.venv/bin/python -m telegrambot weekend
