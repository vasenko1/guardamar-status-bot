#!/data/data/com.termux/files/usr/bin/sh

# Add only this managed cron block; never replace another bot's jobs.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
TRIGGER="$SCRIPT_DIR/trigger-guardamar-capacity.sh"
DISPATCHER="$SCRIPT_DIR/dispatch-guardamar-capacity.py"
PYTHON="$PROJECT_DIR/.venv/bin/python"
BACKUP_DIR="$HOME/.cache/crontab"
BACKUP="$BACKUP_DIR/crontab.before-capacity"
CURRENT=$(mktemp)
UPDATED=$(mktemp)
ERRORS=$(mktemp)
BEGIN_MARKER='# BEGIN guardamar-status capacity backstop'
END_MARKER='# END guardamar-status capacity backstop'
JOB="12,27,42,57 * * * * $TRIGGER"

cleanup() {
    rm -f "$CURRENT" "$UPDATED" "$ERRORS"
}
trap cleanup EXIT HUP INT TERM

if [ ! -x "$TRIGGER" ] || [ ! -x "$PYTHON" ]; then
    echo "ERROR: capacity wrapper or project Python is not executable" >&2
    exit 1
fi
if ! "$PYTHON" "$DISPATCHER" --check-token; then
    echo "ERROR: capacity token file is missing or unsafe" >&2
    exit 1
fi

if ! crontab -l >"$CURRENT" 2>"$ERRORS"; then
    if ! grep -qi 'no crontab for' "$ERRORS"; then
        echo "ERROR: could not safely read current crontab" >&2
        exit 1
    fi
fi
if ! awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { if (active || begins) invalid = 1; active = 1; begins++; next }
    $0 == end { if (!active || ends) invalid = 1; active = 0; ends++; next }
    END { if (invalid || active || begins != ends) exit 1 }
' "$CURRENT"; then
    echo "ERROR: capacity cron block is malformed" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
if [ ! -e "$BACKUP" ]; then
    cp "$CURRENT" "$BACKUP"
fi
awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { managed = 1; next }
    $0 == end { managed = 0; next }
    !managed { print }
' "$CURRENT" >"$UPDATED"
printf '%s\n%s\n%s\n' "$BEGIN_MARKER" "$JOB" "$END_MARKER" >>"$UPDATED"
crontab "$UPDATED"

sv up crond
crontab -l >"$CURRENT"
awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin { managed = 1 }
    managed { print }
    $0 == end { managed = 0 }
' "$CURRENT"
sv status crond
