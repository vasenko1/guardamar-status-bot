#!/data/data/com.termux/files/usr/bin/sh

# One-shot GitHub dispatcher; never loads the bot's .env or OCI credentials.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
LOG="$PROJECT_DIR/state/capacity-backstop.log"
RUNTIME_LOCK="$PROJECT_DIR/state/code-runtime.lock"

. "$SCRIPT_DIR/runtime-lock.sh"

mkdir -p "$PROJECT_DIR/state" || exit 1
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1" || exit 1
fi
exec >>"$LOG" 2>&1

if ! acquire_runtime_lock "$RUNTIME_LOCK"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP runtime_lock_busy"
    exit 0
fi
trap 'release_runtime_lock "$RUNTIME_LOCK"' EXIT HUP INT TERM

cd "$PROJECT_DIR" || exit 1
"$PROJECT_DIR/.venv/bin/python" "$SCRIPT_DIR/dispatch-guardamar-capacity.py"
