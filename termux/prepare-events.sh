#!/data/data/com.termux/files/usr/bin/sh
set -eu
PROJECT=/data/data/com.termux/files/home/bots/guardamar-status
cd "$PROJECT"
set -a
. ./.env
set +a

exec >> state/event-preparation.log 2>&1
./.venv/bin/python -m telegrambot prepare-event-translations
./.venv/bin/python -m telegrambot.federation_event_translations
