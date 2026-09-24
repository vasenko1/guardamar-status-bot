#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
MONITOR="$PROJECT_DIR/termux/monitor-traffic.sh"
BACKUP_DIR="$HOME/.cache/crontab"
BACKUP="$BACKUP_DIR/crontab.before-traffic"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status traffic monitor'
END_MARKER='# END guardamar-status traffic monitor'
JOB="37 * * * * $MONITOR"

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$MONITOR" ]; then
    echo "ERROR: monitor-traffic.sh is not executable" >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR/state" "$BACKUP_DIR"
if ! crontab -l >"$CURRENT" 2>"$ERRORS"; then
    if ! grep -qi 'no crontab for' "$ERRORS"; then
        echo "ERROR: could not safely read current crontab" >&2
        exit 1
    fi
fi
if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { if (active || begins > 0) exit 2; active = 1; begins++; next }
    $0 == end { if (!active || ends > 0) exit 2; active = 0; ends++; next }
    END { if (active || begins != ends) exit 2 }
' "$CURRENT"; then
    echo "ERROR: traffic cron block is malformed" >&2
    exit 1
fi
if [ ! -f "$BACKUP" ]; then
    cp "$CURRENT" "$BACKUP"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v job="$JOB" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 != job { print }
' "$CURRENT" >"$UPDATED"

{
    cat "$UPDATED"
    printf '%s\n%s\n%s\n' "$BEGIN_MARKER" "$JOB" "$END_MARKER"
} | crontab -

sv up crond
echo "Traffic monitor installed: hourly at :37 Europe/Madrid"
crontab -l
