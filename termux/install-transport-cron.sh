#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
SYNC="$PROJECT_DIR/termux/sync-transport.sh"
PUBLISH="$PROJECT_DIR/termux/publish-transport-notifications.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status transport sync'
END_MARKER='# END guardamar-status transport sync'

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$SYNC" ]; then
    echo "ОШИБКА: sync-transport.sh не найден или не исполняемый" >&2
    exit 1
fi
if [ ! -f "$PUBLISH" ]; then
    echo "ОШИБКА: publish-transport-notifications.sh не найден" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
if ! crontab -l >"$CURRENT" 2>"$ERRORS"; then
    if ! grep -qi 'no crontab for' "$ERRORS"; then
        echo "ОШИБКА: не удалось безопасно прочитать текущий crontab" >&2
        exit 1
    fi
fi

if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {
        if (active || begins > 0) { exit 2 }
        active = 1
        begins++
        next
    }
    $0 == end {
        if (!active || ends > 0) { exit 2 }
        active = 0
        ends++
        next
    }
    END {
        if (active || begins != ends) { exit 2 }
    }
' "$CURRENT"; then
    echo "ОШИБКА: повреждён служебный блок transport sync в crontab" >&2
    exit 1
fi

if [ ! -f "$BACKUP_DIR/crontab.before-transport" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-transport"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v publish="$PUBLISH" -v shbin="$SH_BIN" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 == "30 12 * * * " shbin " " publish { next }
    $0 == "42 8 * * * " shbin " " publish { next }
    { print }
' "$CURRENT" >"$UPDATED"
mv "$UPDATED" "$CURRENT"

{
    cat "$CURRENT"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "0 5 * * * $SYNC" \
        "42 8 * * * $SH_BIN $PUBLISH" \
        "$END_MARKER"
} | crontab -

sv up crond
echo "Транспорт: синхронизация 05:00, уведомления 08:42 Europe/Madrid"
