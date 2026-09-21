#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
SYNC="$PROJECT_DIR/termux/sync-guide.sh"
BATHING="$PROJECT_DIR/termux/sync-bathing-water.sh"
PUBLISH="$PROJECT_DIR/termux/publish-course-notifications.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status guide sync'
END_MARKER='# END guardamar-status guide sync'

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$SYNC" ]; then
    echo "ОШИБКА: sync-guide.sh не найден" >&2
    exit 1
fi
if [ ! -f "$BATHING" ]; then
    echo "ОШИБКА: sync-bathing-water.sh не найден" >&2
    exit 1
fi
if [ ! -f "$PUBLISH" ]; then
    echo "ОШИБКА: publish-course-notifications.sh не найден" >&2
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
    echo "ОШИБКА: повреждён служебный блок guide sync в crontab" >&2
    exit 1
fi

if [ ! -f "$BACKUP_DIR/crontab.before-guide" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-guide"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v sync="$SYNC" -v bathing="$BATHING" -v publish="$PUBLISH" -v shbin="$SH_BIN" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 == "30 16 * * * " shbin " " sync { next }
    $0 == "35 19 * 6-8 * " shbin " " bathing { next }
    $0 == "35 19 1-20 9 * " shbin " " bathing { next }
    $0 == "42 9,11 * * * " shbin " " publish { next }
    { print }
' "$CURRENT" >"$UPDATED"
mv "$UPDATED" "$CURRENT"

{
    cat "$CURRENT"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "2 9 * * * $SH_BIN $SYNC" \
        "35 19 * 6-8 * $SH_BIN $BATHING" \
        "35 19 1-20 9 * $SH_BIN $BATHING" \
        "45 19 14 6 * $SH_BIN $SYNC" \
        "45 19 15 9 * $SH_BIN $SYNC" \
        "42 9,11 * * * $SH_BIN $PUBLISH" \
        "$END_MARKER"
} | crontab -

sv up crond
echo "Справочник: 09:02 ежедневно; зоны купания 19:35 ежедневно 01.06-20.09; Zona Azul 19:45 14.06/15.09; занятия 09:42 и retry 11:42 Europe/Madrid"
