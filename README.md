# Lightweight Telegram Bot

A small Telegram bot designed to run reliably in Termux on a low-powered
Android device.

The planned first feature is a concise Morning Digest covering local weather,
sea conditions, beach flags, warnings, municipal updates, and relevant events.
The architecture reserves one additional feature slot without defining it
prematurely.

## Current status

The Morning Digest MVP can fetch official AEMET weather and warning data plus
Guardamar's public SafeBeach status, format one short message, and deliver it
to one configured Telegram chat or channel. It may also include all verified
deduplicated Guardamar events occurring today and an explicit active
festival traffic restriction from Policía Local Guardamar.

## Repository map

- `docs/kb/` — stable project knowledge for people and coding agents
- `research/` — source investigations and time-sensitive findings
- `adr/` — architecture decision records
- `src/` — application code
- `tests/` — automated tests

## Start here

Read [AGENTS.md](AGENTS.md) before making changes. The knowledge base begins
with [docs/kb/00_Project_Overview.md](docs/kb/00_Project_Overview.md).

## Runtime direction

- Python with `asyncio`
- standard-library HTTP for sources and outbound Telegram delivery
- one short-lived 07:30 process and bounded seasonal update checks
- optional isolated listener for allowlisted private `/preview`
- one atomic JSON value for the last successful local date
- no Docker, PostgreSQL, webhooks, or heavy background services
- no internal scheduler, continuous polling, resident collectors, or generic
  cache layer

The Python `tzdata` package is the only runtime dependency. It supplies the
`Europe/Madrid` timezone on Termux builds that do not expose Android's system
timezone database to Python.

## Configuration

Request keys from
[AEMET OpenData](https://opendata.aemet.es/centrodedescargas/inicio) and the
[ESIOS API personal-token page](https://api.esios.ree.es/doc/index.html), then
create a bot with Telegram's BotFather.

```sh
export AEMET_API_KEY="your-key"
export ESIOS_API_KEY="your-personal-esios-key"
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="@your-channel-or-chat-id"
export TELEGRAM_ALLOWED_USER_IDS="your-private-telegram-user-id"
export GEMINI_API_KEY="your-optional-gemini-key"
export OPENROUTER_API_KEY="your-optional-fallback-key"
```

Morning state defaults to `state/delivery.json`; override it with
`MORNING_DIGEST_STATE_PATH` if needed. Electricity publication state defaults
to `state/electricity.json`, and its private normalized target-day data defaults
to `state/electricity_prices.json`; override the latter with
`ELECTRICITY_SNAPSHOT_PATH` if needed. The state and snapshot paths must remain
different. Secrets must not be committed.

## Run

Run the early Morning Digest execution:

```sh
PYTHONPATH=src python -m telegrambot run
```

The command collects the approved sources without operational SafeBeach rows,
sends the briefing, stores its Telegram message ID, and exits.

Use external Termux cron entries at `07:30` and every five minutes from
`10:10` through `10:40` in `Europe/Madrid`:

```cron
CRON_TZ=Europe/Madrid
10 5 * * * /path/to/TelegramBot/termux/sync-municipal-events.sh
30 5 * * * /path/to/TelegramBot/termux/sync-agenda-events.sh
0,30 6 * * * /path/to/TelegramBot/termux/prepare-events.sh
0 7 * * * /path/to/TelegramBot/termux/prepare-events.sh
15 7 * * * /path/to/TelegramBot/termux/prepare-aemet.sh
30 7 * * * /path/to/TelegramBot/termux/run-daily.sh
10-40/5 10 * * * /path/to/TelegramBot/termux/update-daily.sh
0,5,10 11,13,15,17,19 * 7,8 * /path/to/TelegramBot/termux/monitor-updates.sh
0,5,10 12,14,16,18 20-30 6 * /path/to/TelegramBot/termux/monitor-updates.sh
0,5,10 12,14,16,18 1-14 9 * /path/to/TelegramBot/termux/monitor-updates.sh
0 20 20-30 6 * /path/to/TelegramBot/termux/monitor-updates.sh
0 20 1-14 9 * /path/to/TelegramBot/termux/monitor-updates.sh
0 11,15,19 * 1-5,10-12 * /path/to/TelegramBot/termux/monitor-updates.sh
0 11,15,19 1-19 6 * /path/to/TelegramBot/termux/monitor-updates.sh
0 11,15,19 15-30 9 * /path/to/TelegramBot/termux/monitor-updates.sh
30,35,45 20 * * * /path/to/TelegramBot/termux/run-electricity.sh
0,20 21 * * * /path/to/TelegramBot/termux/run-electricity.sh
0,20 18 * * 5 /path/to/TelegramBot/termux/run-weekend.sh
0 19 * * 5 /path/to/TelegramBot/termux/run-weekend.sh
```

Keep the Android device timezone set to `Europe/Madrid` as an additional
safeguard.

The validated Android deployment uses the scripts in `termux/`:

- `termux/listen.sh` under a `termux-services` service named
  `guardamar-preview`; its `run` file may be a symlink because the launcher
  resolves the real target path before loading the project `.env`;
- `termux/run-daily.sh` at 07:30 and `termux/update-daily.sh` every five
  minutes from 10:10 through 10:40;
- `termux/monitor-updates.sh` at the bounded seasonal beach windows and the
  three daily AEMET warning windows documented in ADR 0031;
- `termux/sync-municipal-events.sh` at 05:10 and
  `termux/sync-agenda-events.sh` at 05:30 to atomically refresh small event
  catalogs before publication;
- `termux/prepare-events.sh` at 06:00, 06:30, and 07:00 to fill only missing
  title translations, and `termux/prepare-aemet.sh` at 07:15 to store one
  normalized same-day weather snapshot;
- `termux/deploy.sh` at `04:00` to apply only commits promoted to the
  GitHub `deploy` branch after successful CI;
- `termux/start-services` copied to `~/.termux/boot/start-services` for the
  F-Droid Termux:Boot add-on.

The deployment check is a short daily process, not a resident agent. It
requires a Git checkout with the repository configured as `origin`. It refuses
tracked local changes and non-fast-forward history, installs declared Python
dependencies, reruns the test suite on the phone, and restarts only the
private preview listener. On installation or test failure it restores the
previous commit. `.env`, `state/`, logs, and the virtual environment remain
local and are never pulled from GitHub.

Recommended crontab entries:

```cron
CRON_TZ=Europe/Madrid
0 4 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/deploy.sh
10 5 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/sync-municipal-events.sh
30 5 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/sync-agenda-events.sh
0,30 6 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/prepare-events.sh
0 7 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/prepare-events.sh
15 7 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/prepare-aemet.sh
30 7 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/run-daily.sh
10-40/5 10 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/update-daily.sh
0,5,10 11,13,15,17,19 * 7,8 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0,5,10 12,14,16,18 20-30 6 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0,5,10 12,14,16,18 1-14 9 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0 20 20-30 6 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0 20 1-14 9 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0 11,15,19 * 1-5,10-12 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0 11,15,19 1-19 6 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
0 11,15,19 15-30 9 * /data/data/com.termux/files/home/bots/guardamar-status/termux/monitor-updates.sh
30,35,45 20 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/run-electricity.sh
0,20 21 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/run-electricity.sh
0,20 18 * * 5 /data/data/com.termux/files/home/bots/guardamar-status/termux/run-weekend.sh
0 19 * * 5 /data/data/com.termux/files/home/bots/guardamar-status/termux/run-weekend.sh
```

After deployment, install only the operational-monitor entries without
overwriting cron jobs belonging to this or another bot:

```sh
cd ~/bots/guardamar-status
./termux/install-monitor-cron.sh
```

The installer saves the original crontab once as
`~/.cache/crontab/crontab.before-monitor`, preserves unrelated lines, and owns
only its clearly marked operational-monitor block. Repeated execution replaces
that block and removes exact legacy copies of its eight jobs. A final scoped
`CRON_TZ=Europe/Madrid` prevents another bot's timezone setting from changing
this schedule. The installer does not install or modify the other Morning
Digest and electricity entries listed above.

Install `cronie`, `termux-services`, and the Python `tzdata` dependency before
enabling the services. Open Termux:Boot once after installation. On Android,
allow Termux and Termux:Boot to auto-start and run without battery
restrictions. The boot script holds a wake lock for reliable cron execution.

Local inspection remains available:

```sh
PYTHONPATH=src python -m telegrambot preview
PYTHONPATH=src python -m telegrambot status
PYTHONPATH=src python -m telegrambot electricity-preview
PYTHONPATH=src python -m telegrambot weekend-preview
PYTHONPATH=src python -m telegrambot refresh-current
```

- `preview` collects and prints without Telegram or publication state.
- `status` prints the last successfully published local date.
- `electricity-preview` prints tomorrow's table and its explanatory reply
  without publishing or changing publication state. It reuses, or creates
  after one complete ESIOS response, the same private normalized target-day
  snapshot used by publication. It shares the electricity publication lock,
  so a simultaneous cron run exits safely instead of duplicating the request.
- `refresh-current` is an explicit operator action that rebuilds today's
  digest and edits its one live Telegram message in place. It never creates a
  replacement message and refuses to act without a trusted current-day state.

To enable private Telegram previews, run the independent listener:

```sh
PYTHONPATH=src python -m telegrambot listen
```

Send `/preview` to the bot in a private chat. Only IDs in
`TELEGRAM_ALLOWED_USER_IDS` are accepted. The reply is silent, is never sent
to the configured group, and does not change publication state. The listener
does not fetch any source until an authorized command arrives.

State contains only the current local date, publication time, Telegram
message IDs, cleanup result, and the isolated electricity publication marker
plus one normalized 24-hour target-day snapshot. AEMET recovery retries only
bounded transient failures and repeats the complete two-step product request.
If AEMET remains unavailable during a later update, the same-day prepared
AEMET snapshot supplies the weather blocks. No raw source cache is
implemented.

Gemini is used only for the bounded municipal AI tasks documented in ADRs
0011, 0012, and 0028. If `OPENROUTER_API_KEY` is configured, one pinned
non-Google model may receive the same public input and JSON schema after a
Gemini failure. Known notices use deterministic rules and consume no model
quota. Any double provider error or failed source-fact validation omits only
the affected optional contribution or preserves its prior valid snapshot.

ADRs 0012 and 0028 implement two bounded normalized event catalogs. Official
monthly HTML is primary; a changed linked MUPI is supplementary and accepted
only after two agreeing structured reads.

The current temperature and wind come from AEMET's Rojales station, the
nearest station listed by AEMET for Guardamar (5.3 km away). SafeBeach
contributes the active Platja Centre flag and its sea temperature when
available. Otherwise AEMET Centro / La Roqueta may supply today's forecast
water temperature; it never supplies the flag. The two official agenda inputs
may contribute all verified deduplicated events relevant today.
Optional-source failure does not block the weather digest.

Run the standard-library test suite with:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```
