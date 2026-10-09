#!/data/data/com.termux/files/usr/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
RUNNER="$PROJECT_DIR/termux/run-supermarket-closures.sh"
SH_BIN=$(command -v sh)
BACKUP_DIR="$HOME/.cache/crontab"
BACKUP="$BACKUP_DIR/crontab.before-supermarket-closures"
mkdir -p "$BACKUP_DIR"
CURRENT=$(mktemp "$BACKUP_DIR/supermarket-current.XXXXXX")
UPDATED=$(mktemp "$BACKUP_DIR/supermarket-updated.XXXXXX")
ERRORS=$(mktemp "$BACKUP_DIR/supermarket-errors.XXXXXX")
BEGIN_MARKER='# BEGIN guardamar-status supermarket closures'
END_MARKER='# END guardamar-status supermarket closures'
JOB="15 8 * * * $SH_BIN $RUNNER"

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -f "$RUNNER" ]; then
    echo "ERROR: run-supermarket-closures.sh not found" >&2
    exit 1
fi

mkdir -p "$PROJECT_DIR/state"

if ! crontab -l >"$CURRENT" 2>"$ERRORS"; then
    if ! grep -qi 'no crontab for' "$ERRORS"; then
        echo "ERROR: could not safely read current crontab" >&2
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
    echo "ERROR: supermarket closure cron block is malformed" >&2
    exit 1
fi

if [ ! -f "$BACKUP" ]; then
    cp "$CURRENT" "$BACKUP"
fi

awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v runner="$RUNNER" -v shbin="$SH_BIN" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    managed { next }
    $0 == "15 8 * * * " shbin " " runner { next }
    { print }
' "$CURRENT" >"$UPDATED"

{
    cat "$UPDATED"
    printf '%s\n' \
        "$BEGIN_MARKER" \
        'CRON_TZ=Europe/Madrid' \
        "$JOB" \
        "$END_MARKER"
} | crontab -

echo "Supermarket closure notices installed: one daily check at 08:15 Europe/Madrid"
crontab -l
