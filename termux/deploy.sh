#!/data/data/com.termux/files/usr/bin/sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
STATE_DIR="$PROJECT_DIR/state"
LOG="$STATE_DIR/deploy.log"
LOCK_DIR="$STATE_DIR/deploy.lock"
RUNTIME_LOCK_DIR="$STATE_DIR/code-runtime.lock"
RUNTIME_LOCK_HELD=0

. "$SCRIPT_DIR/runtime-lock.sh"

mkdir -p "$STATE_DIR"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
    mv "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

echo "$(date '+%Y-%m-%d %H:%M:%S') INFO Checking tested deployment"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP Another deployment is running"
    exit 0
fi
cleanup() {
    if [ "$RUNTIME_LOCK_HELD" -eq 1 ]; then
        release_runtime_lock "$RUNTIME_LOCK_DIR"
    fi
    rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT HUP INT TERM

if ! acquire_runtime_lock "$RUNTIME_LOCK_DIR"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') SKIP Application task is running"
    exit 0
fi
RUNTIME_LOCK_HELD=1

cd "$PROJECT_DIR" || exit 1

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Tracked local changes prevent deployment"
    exit 1
fi

if ! git fetch --quiet origin deploy; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Could not fetch deploy branch"
    exit 1
fi

CURRENT_SHA=$(git rev-parse HEAD) || exit 1
DEPLOY_SHA=$(git rev-parse FETCH_HEAD) || exit 1

install_runtime_jobs() {
    if [ ! -x "$PROJECT_DIR/termux/install-earthquake-cron.sh" ]; then
        return 0
    fi
    if ! "$PROJECT_DIR/termux/install-earthquake-cron.sh"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Could not install earthquake schedule"
        return 1
    fi
}

if [ "$CURRENT_SHA" = "$DEPLOY_SHA" ]; then
    install_runtime_jobs || exit 1
    echo "$(date '+%Y-%m-%d %H:%M:%S') INFO Already up to date"
    exit 0
fi

if ! git merge-base --is-ancestor "$CURRENT_SHA" "$DEPLOY_SHA"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Deploy branch is not a fast-forward"
    exit 1
fi

if ! git merge --quiet --ff-only "$DEPLOY_SHA"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Could not apply tested commit"
    exit 1
fi

rollback() {
    git reset --quiet --hard "$CURRENT_SHA"
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Deployment rolled back to $CURRENT_SHA"
    exit 1
}

if ! ./.venv/bin/python -m pip install --quiet --disable-pip-version-check .; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Dependency installation failed"
    rollback
fi

if ! PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Device tests failed"
    rollback
fi

# Reconcile the idempotent managed cron block after every code update. The
# no-op path above also retries this step, so a temporary crond failure cannot
# leave a successfully deployed feature permanently inactive.
install_runtime_jobs || exit 1

# Refresh the small official rota after a successful code update so schema or
# zone-selection fixes take effect immediately. Pharmacy data is optional; an
# unreachable college must not roll back otherwise valid application code,
# and the weekly job remains the bounded recovery path.
if ! PYTHONPATH=src ./.venv/bin/python -m telegrambot sync-pharmacy; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') WARNING Pharmacy refresh failed; weekly sync will retry"
fi

if ! sv restart guardamar-preview; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') FAILURE Code updated but preview listener did not restart"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') SUCCESS Deployed $DEPLOY_SHA"
