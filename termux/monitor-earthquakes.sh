#!/data/data/com.termux/files/usr/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

LOG="$PROJECT_DIR/state/earthquakes.log"
DEPLOY_LOCK="$PROJECT_DIR/state/deploy.lock"

mkdir -p "$PROJECT_DIR/state"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

exec >>"$LOG" 2>&1

if [ -d "$DEPLOY_LOCK" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP Deployment is running"
    exit 0
fi

exec ./.venv/bin/python -m telegrambot monitor-earthquakes
