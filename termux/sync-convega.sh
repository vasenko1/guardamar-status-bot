#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
STATE_DIR="$PROJECT_DIR/state"
LOG="$STATE_DIR/convega.log"
RUNTIME_LOCK="$STATE_DIR/code-runtime.lock"

. "$SCRIPT_DIR/runtime-lock.sh"

mkdir -p "$STATE_DIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 524288 ]; then
    mv "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

if ! acquire_runtime_lock "$RUNTIME_LOCK"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP runtime_lock_busy"
    exit 0
fi
trap 'release_runtime_lock "$RUNTIME_LOCK"' EXIT HUP INT TERM

cd "$PROJECT_DIR"
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

./.venv/bin/python -m telegrambot.convega
