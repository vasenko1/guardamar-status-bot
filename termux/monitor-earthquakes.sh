#!/data/data/com.termux/files/usr/bin/sh

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

LOG="$PROJECT_DIR/state/earthquakes.log"
RUNTIME_LOCK="$PROJECT_DIR/state/code-runtime.lock"

. "$SCRIPT_DIR/runtime-lock.sh"

mkdir -p "$PROJECT_DIR/state"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi

exec >>"$LOG" 2>&1

if ! acquire_runtime_lock "$RUNTIME_LOCK"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP Deployment or monitor is running"
    exit 0
fi
trap 'release_runtime_lock "$RUNTIME_LOCK"' EXIT HUP INT TERM

./.venv/bin/python -m telegrambot monitor-earthquakes
