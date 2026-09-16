#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
STATE_DIR="$PROJECT_DIR/state"
LOG="$STATE_DIR/guide.log"

mkdir -p "$STATE_DIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 524288 ]; then
    mv "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

cd "$PROJECT_DIR"
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

./.venv/bin/python -m telegrambot.guide sync

# Notifications consume only the accepted Sporttia/Telegram state written above.
# They have their own fail-closed delivery state, so a notification ambiguity must
# never undo or block the already-completed guide reconciliation.
if ! ./.venv/bin/python -m telegrambot.sports_notifications_runner; then
    echo "Sports notification sync deferred; guide sync remains complete" >&2
fi
