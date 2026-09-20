#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
SYNC="$PROJECT_DIR/termux/sync-guide.sh"
PUBLISH="$PROJECT_DIR/termux/publish-course-notifications.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status guide sync'
END_MARKER='# END guardamar-status guide sync'

cleanup() {
    rm -f "$CURRENT"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$SYNC" ]; then
    echo "ОШИБКА: sync-guide.sh не найден" >&2
    exit 1
fi
if [ ! -f "$PUBLISH" ]; then
    echo "ОШИБКА: publish-course-notifications.sh не найден" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
crontab -l >"$CURRENT" 2>/dev/null || true
if [ ! -f "$BACKUP_DIR/crontab.before-guide" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-guide"
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
        "2 9 * * * $SH_BIN $SYNC" \
        "42 9,11 * * * $SH_BIN $PUBLISH" \
        "$END_MARKER"
} | crontab -

sv up crond
echo "Справочник: синхронизация 09:02; уведомления о занятиях 09:42 и retry 11:42 Europe/Madrid"
