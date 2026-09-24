#!/data/data/com.termux/files/usr/bin/sh

# Install event-planning notices, preserving every other cron job.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
WEEKEND="$PROJECT_DIR/termux/run-weekend.sh"
TOMORROW="$PROJECT_DIR/termux/run-tomorrow-events.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
JOBS=$(mktemp)
NEXT=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status weekend digest'
END_MARKER='# END guardamar-status weekend digest'

cleanup() {
    rm -f "$CURRENT" "$JOBS" "$NEXT"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$WEEKEND" ]; then
    echo "ОШИБКА: run-weekend.sh не найден или не исполняемый" >&2
    exit 1
fi
if [ ! -f "$TOMORROW" ]; then
    echo "ОШИБКА: run-tomorrow-events.sh не найден" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
crontab -l >"$CURRENT" 2>/dev/null || true
if [ ! -f "$BACKUP_DIR/crontab.before-weekend" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-weekend"
fi

if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { begin_count++; inside++; next }
    $0 == end { end_count++; if (!inside) invalid = 1; inside--; next }
    END { exit (begin_count == end_count && !inside && begin_count <= 1 && !invalid) ? 0 : 1 }
' "$CURRENT"; then
    echo "ОШИБКА: блок афиши выходных в crontab повреждён; ничего не изменено" >&2
    exit 1
fi

printf '%s\n' \
    "15 19 * * 5 $WEEKEND --fresh" \
    "15 20 * * 5 $WEEKEND" \
    "25 19 * * 0-4 $SH_BIN $TOMORROW" \
    >"$JOBS"

if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v weekend="$WEEKEND" -v tomorrow="$TOMORROW" -v shbin="$SH_BIN" '
    NR == FNR { jobs[$0] = 1; next }
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed && $0 == "0,20 18 * * 5 " weekend { next }
    !managed && $0 == "0 19 * * 5 " weekend { next }
    !managed && $0 == "25 19 * * 0-4 " shbin " " tomorrow { next }
    !managed && !($0 in jobs) { print }
' "$JOBS" "$CURRENT" >"$NEXT"; then
    echo "ОШИБКА: не удалось подготовить новый crontab; ничего не изменено" >&2
    exit 1
fi

printf '%s\n' \
    "$BEGIN_MARKER" \
    'CRON_TZ=Europe/Madrid' \
    "$(cat "$JOBS")" \
    "$END_MARKER" \
    >>"$NEXT"

crontab "$NEXT"
sv up crond
