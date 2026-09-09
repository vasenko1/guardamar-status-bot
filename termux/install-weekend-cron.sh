#!/data/data/com.termux/files/usr/bin/sh

# Install only the Friday weekend-digest jobs, preserving every other cron job.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
WEEKEND="$PROJECT_DIR/termux/run-weekend.sh"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
JOBS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status weekend digest'
END_MARKER='# END guardamar-status weekend digest'

cleanup() {
    rm -f "$CURRENT" "$JOBS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$WEEKEND" ]; then
    echo "ОШИБКА: run-weekend.sh не найден или не исполняемый" >&2
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
    "0,20 18 * * 5 $WEEKEND" \
    "0 19 * * 5 $WEEKEND" \
    >"$JOBS"

{
    awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
        NR == FNR { jobs[$0] = 1; next }
        $0 == begin { managed = 1; next }
        $0 == end { managed = 0; next }
        !managed && !($0 in jobs) { print }
    ' "$JOBS" "$CURRENT"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "$(cat "$JOBS")" \
        "$END_MARKER"
} | crontab -

sv up crond
