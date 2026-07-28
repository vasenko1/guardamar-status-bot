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
daily to one configured Telegram chat or channel. It may also include up to
two official Agenda Guardamar events occurring today and an explicit active
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
- one short-lived process invoked externally at 10:00
- optional isolated listener for allowlisted private `/preview`
- one atomic JSON value for the last successful local date
- no Docker, PostgreSQL, webhooks, or heavy background services
- no internal scheduler, source polling, collectors, or cache layer

The Python `tzdata` package is the only runtime dependency. It supplies the
`Europe/Madrid` timezone on Termux builds that do not expose Android's system
timezone database to Python.

## Configuration

Request an API key from
[AEMET OpenData](https://opendata.aemet.es/centrodedescargas/inicio) and create
a bot with Telegram's BotFather.

```sh
export AEMET_API_KEY="your-key"
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="@your-channel-or-chat-id"
export TELEGRAM_ALLOWED_USER_IDS="your-private-telegram-user-id"
export GEMINI_API_KEY="your-optional-gemini-key"
```

State defaults to `state/delivery.json`; override it with
`MORNING_DIGEST_STATE_PATH` if needed. Secrets must not be committed.

## Run

Run one complete Morning Digest execution:

```sh
PYTHONPATH=src python -m telegrambot run
```

The command checks the successful publication date, collects every implemented
source directly once, builds and sends the digest, stores the date after
confirmed success, and exits.

Use an external Termux scheduler to invoke this command at `10:00` in
`Europe/Madrid`. For example, a `cronie` entry can invoke a small local shell
command that changes to the repository, loads `.env`, and runs the command:

```cron
CRON_TZ=Europe/Madrid
0 10 * * * cd /path/to/TelegramBot && bash -lc 'source .env; PYTHONPATH=src python -m telegrambot run'
```

Keep the Android device timezone set to `Europe/Madrid` as an additional
safeguard.

The validated Android deployment uses the scripts in `termux/`:

- `termux/listen.sh` under a `termux-services` service named
  `guardamar-preview`; its `run` file may be a symlink because the launcher
  resolves the real target path before loading the project `.env`;
- `termux/run-daily.sh` from this crontab:
  `CRON_TZ=Europe/Madrid` and `0 10 * * * .../termux/run-daily.sh`;
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
0 10 * * * /data/data/com.termux/files/home/bots/guardamar-status/termux/run-daily.sh
```

Install `cronie`, `termux-services`, and the Python `tzdata` dependency before
enabling the services. Open Termux:Boot once after installation. On Android,
allow Termux and Termux:Boot to auto-start and run without battery
restrictions. The boot script holds a wake lock for reliable exact-time cron
execution; remove that line if battery use is more important than exact 10:00
delivery.

Local inspection remains available:

```sh
PYTHONPATH=src python -m telegrambot preview
PYTHONPATH=src python -m telegrambot status
```

- `preview` collects and prints without Telegram or publication state.
- `status` prints the last successfully published local date.

To enable private Telegram previews, run the independent listener:

```sh
PYTHONPATH=src python -m telegrambot listen
```

Send `/preview` to the bot in a private chat. Only IDs in
`TELEGRAM_ALLOWED_USER_IDS` are accepted. The reply is silent, is never sent
to the configured group, and does not change publication state. The listener
does not fetch any source until an authorized command arrives.

No state is written for collection or delivery failure. No source cache is
currently implemented: source responses and normalized records live only for
the current process and are discarded when it exits. The empty lock file
beside the state file only prevents overlapping processes; it contains no
cached data.

Gemini is optional and is called only when the official Policía Local traffic
page contains an unknown notice format. Known notices use deterministic rules
and consume no model quota. Any Gemini error or failed source-fact validation
silently omits the traffic section.

ADR 0012 implements a bounded structured monthly-event snapshot populated by
change-triggered Gemini Vision extraction of the official linked poster.

The current temperature and wind come from AEMET's Rojales station, the
nearest station listed by AEMET for Guardamar (5.3 km away). SafeBeach
contributes the active Platja Centre flag and its sea temperature when
available. Otherwise AEMET Centro / La Roqueta may supply today's forecast
water temperature; it never supplies the flag. The two official agenda inputs
may contribute up to two events relevant today. Optional-source failure does not block the
weather digest.

Run the standard-library test suite with:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
```
