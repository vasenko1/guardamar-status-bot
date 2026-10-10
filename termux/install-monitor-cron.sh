#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MONITOR="$PROJECT_DIR/termux/monitor-updates.sh"
TERMUX_PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
CROND_SVDIR="${SVDIR:-$TERMUX_PREFIX/var/service}"
CROND_SERVICE="$CROND_SVDIR/crond"
BACKUP_DIR="$HOME/.cache/crontab"
CURRENT=$(mktemp)
JOBS=$(mktemp)
NEXT=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status operational monitor'
END_MARKER='# END guardamar-status operational monitor'

cleanup() {
    rm -f "$CURRENT" "$JOBS" "$NEXT" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$MONITOR" ]; then
    echo "ОШИБКА: monitor-updates.sh не найден или не исполняемый" >&2
    exit 1
fi

crond_running() {
    pgrep -x crond >/dev/null 2>&1
}

if ! crond_running && [ ! -d "$CROND_SERVICE" ]; then
    echo "ОШИБКА: crond не запущен и service directory отсутствует: $CROND_SERVICE" >&2
    echo "Установите/настройте termux-services или запустите crond до изменения crontab." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
if ! crontab -l >"$CURRENT" 2>"$ERRORS"; then
    if ! grep -qi 'no crontab for' "$ERRORS"; then
        echo "ОШИБКА: не удалось безопасно прочитать текущий crontab; ничего не изменено" >&2
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
    echo "ОШИБКА: повреждён служебный блок operational monitor в crontab; ничего не изменено" >&2
    exit 1
fi

if [ ! -f "$BACKUP_DIR/crontab.before-monitor" ]; then
    cp "$CURRENT" "$BACKUP_DIR/crontab.before-monitor"
fi

printf '%s\n' \
    "51 7-23 * * * $MONITOR" \
    "0,5,10 11,13,15,17,19 * 7,8 * $MONITOR" \
    "0,5,10 12,14,16,18 * 6,9 * $MONITOR" \
    "0,5,10 12,14,16,18 * 10 * $MONITOR" \
    "0,5,10,30,35,40 13 * 10 * $MONITOR" \
    "0 20 * 6,9 * $MONITOR" \
    "0 11,15,19 * 1-5,10-12 * $MONITOR" \
    >"$JOBS"

if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    NR == FNR { jobs[$0] = 1; next }
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    !($0 in jobs) { print }
' "$JOBS" "$CURRENT" >"$NEXT"; then
    echo "ОШИБКА: не удалось подготовить новый crontab; ничего не изменено" >&2
    exit 1
fi

printf '%s\n' "$BEGIN_MARKER" 'CRON_TZ=Europe/Madrid' >>"$NEXT"
cat "$JOBS" >>"$NEXT"
printf '%s\n' "$END_MARKER" >>"$NEXT"

if ! crond_running; then
    if ! SVDIR="$CROND_SVDIR" sv up crond; then
        echo "ОШИБКА: не удалось запустить crond; crontab не изменён" >&2
        exit 1
    fi
fi

if ! crond_running; then
    echo "ОШИБКА: crond не запущен после service startup; crontab не изменён" >&2
    exit 1
fi

crontab "$NEXT"

echo "=== Мониторинг добавлен; остальные задания сохранены ==="
crontab -l
echo "crond: running"