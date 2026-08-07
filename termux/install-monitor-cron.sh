#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MONITOR="$PROJECT_DIR/termux/monitor-updates.sh"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
JOBS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status operational monitor'
END_MARKER='# END guardamar-status operational monitor'

cleanup() {
    rm -f "$CURRENT" "$JOBS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$MONITOR" ]; then
    echo "ОШИБКА: monitor-updates.sh не найден или не исполняемый" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
crontab -l >"$CURRENT" 2>/dev/null || true
if [ ! -f "$BACKUP_DIR/crontab.before-monitor" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-monitor"
fi

printf '%s\n' \
    "0,5,10 11,13,15,17,19 * 7,8 * $MONITOR" \
    "0,5,10 12,14,16,18 20-30 6 * $MONITOR" \
    "0,5,10 12,14,16,18 1-14 9 * $MONITOR" \
    "0 20 20-30 6 * $MONITOR" \
    "0 20 1-14 9 * $MONITOR" \
    "0 11,15,19 * 1-5,10-12 * $MONITOR" \
    "0 11,15,19 1-19 6 * $MONITOR" \
    "0 11,15,19 15-30 9 * $MONITOR" \
    >"$JOBS"

{
    awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
        NR == FNR { jobs[$0] = 1; next }
        $0 == begin { managed = 1; next }
        $0 == end { managed = 0; next }
        managed { next }
        !($0 in jobs) { print }
    ' "$JOBS" "$CURRENT"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "$(cat "$JOBS")" \
        "$END_MARKER"
} | crontab -

sv up crond

echo "=== Мониторинг добавлен; остальные задания сохранены ==="
crontab -l
echo "=== Cron ==="
sv status crond
