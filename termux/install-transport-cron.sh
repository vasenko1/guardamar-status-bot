#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
SYNC="$PROJECT_DIR/termux/sync-transport.sh"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status transport sync'
END_MARKER='# END guardamar-status transport sync'

cleanup() {
    rm -f "$CURRENT"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$SYNC" ]; then
    echo "ОШИБКА: sync-transport.sh не найден или не исполняемый" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
crontab -l >"$CURRENT" 2>/dev/null || true
if [ ! -f "$BACKUP_DIR/crontab.before-transport" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-transport"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed { print }
' "$CURRENT" | {
    cat
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "0 5 * * * $SYNC" \
        "$END_MARKER"
} | crontab -

sv up crond
echo "Транспортная синхронизация установлена на 05:00 Europe/Madrid"
