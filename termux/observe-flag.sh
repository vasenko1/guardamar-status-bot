#!/data/data/com.termux/files/usr/bin/sh

# Temporary research probe. Remove its cron entries after 5–7 days.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
LOG="$PROJECT_DIR/state/safebeach-observation.log"

cd "$PROJECT_DIR" || exit 1
export PYTHONPATH="$PROJECT_DIR/src"

if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

printf '%s ' "$(date '+%Y-%m-%d %H:%M:%S')" >>"$LOG"
./.venv/bin/python -c \
    "import asyncio; from telegrambot.safebeach import fetch_beach_status; print(asyncio.run(fetch_beach_status()))" \
    >>"$LOG" 2>&1
