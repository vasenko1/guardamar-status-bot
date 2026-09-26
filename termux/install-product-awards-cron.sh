#!/data/data/com.termux/files/usr/bin/sh

# Discover award candidates at 13:50 and publish at most one at 14:20.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
RUNNER="$PROJECT_DIR/termux/run-product-awards.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
BACKUP="$BACKUP_DIR/crontab.before-product-awards"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status product awards'
END_MARKER='# END guardamar-status product awards'
DISCOVER_JOB="50 13 * * * $SH_BIN $RUNNER discover"
PUBLISH_JOB="20 14 * * * $SH_BIN $RUNNER publish"

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$RUNNER" ]; then
    echo "ERROR: run-product-awards.sh not found" >&2
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
    echo "ERROR: product-awards cron block is malformed" >&2
    exit 1
fi

if [ ! -f "$BACKUP" ]; then
    cp "$CURRENT" "$BACKUP"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" \
    -v discover="$DISCOVER_JOB" -v publish="$PUBLISH_JOB" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 != discover && $0 != publish { print }
' "$CURRENT" >"$UPDATED"

{
    cat "$UPDATED"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "$DISCOVER_JOB" \
        "$PUBLISH_JOB" \
        "$END_MARKER"
} | crontab -

sv up crond
echo "Product awards installed: discover 13:50, publish 14:20 Europe/Madrid"
crontab -l
