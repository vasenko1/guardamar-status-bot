#!/data/data/com.termux/files/usr/bin/sh

exec 2>&1
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
cd "$PROJECT_DIR" || exit 1
. ./.env
export PYTHONPATH="$PROJECT_DIR/src"

exec ./.venv/bin/python -m telegrambot listen
