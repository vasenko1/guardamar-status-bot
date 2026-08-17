#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MONITOR="$PROJECT_DIR/termux/monitor-earthquakes.sh"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status earthquake monitor'
END_MARKER='# END guardamar-status earthquake monitor'

cleanup() {
    rm -f "$CURRENT" "$UPDATED"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$MONITOR" ]; then
    echo "ОШИБКА: monitor-earthquakes.sh не найден или не исполняемый" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
crontab -l >"$CURRENT" 2>/dev/null || true
if [ ! -f "$BACKUP_DIR/crontab.before-earthquakes" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-earthquakes"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v monitor="$MONITOR" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 == "17 * * * * " monitor { next }
    $0 == "47 * * * * " monitor { next }
    $0 == "55 * * * * " monitor { next }
    { print }
' "$CURRENT" >"$UPDATED"
mv "$UPDATED" "$CURRENT"

{
    cat "$CURRENT"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "55 * * * * $MONITOR" \
        "$END_MARKER"
} | crontab -

sv up crond

echo "Мониторинг землетрясений установлен: каждый час в :55"
