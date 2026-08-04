#!/data/data/com.termux/files/usr/bin/sh
set -eu
PROJECT=/data/data/com.termux/files/home/bots/guardamar-status
cd "$PROJECT"
set -a
. ./.env
set +a
exec ./.venv/bin/python -m telegrambot prepare-aemet \
  >> state/aemet-preparation.log 2>&1
