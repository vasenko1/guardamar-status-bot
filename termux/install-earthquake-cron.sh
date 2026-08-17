#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MONITOR="$PROJECT_DIR/termux/monitor-earthquakes.sh"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status earthquake monitor'
END_MARKER='# END guardamar-status earthquake monitor'

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$MONITOR" ]; then
    echo "ОШИБКА: monitor-earthquakes.sh не найден или не исполняемый" >&2
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
    echo "ОШИБКА: повреждён служебный блок мониторинга в crontab" >&2
    exit 1
fi
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
