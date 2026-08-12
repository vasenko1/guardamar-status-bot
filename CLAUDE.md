# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Required reading

[AGENTS.md](AGENTS.md) is the authoritative contract for changes here and takes
precedence over this file. It requires reading `docs/kb/00`–`04` before any
change. In practice the two that most often decide whether an implementation is
acceptable are [docs/kb/04_Runtime_Constraints.md](docs/kb/04_Runtime_Constraints.md)
(hard limits, prohibited technologies) and
[docs/kb/06_Data_Sources.md](docs/kb/06_Data_Sources.md) (exact per-source
contracts — which product IDs, hosts, fields, and fallbacks are approved).

Documentation has three tiers with different lifetimes: `docs/kb/` is stable
project rules, `adr/` holds durable accepted decisions (indexed in
[docs/kb/10_Decision_Log.md](docs/kb/10_Decision_Log.md)), and `research/` holds
time-sensitive source investigations. Behavior changes usually need the ADR plus
decision-log entry, not just code.

## Commands

Everything runs from the repo root with `PYTHONPATH=src`. There is no build step
and no linter configured; CI runs only the test suite.

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Single module / class / test:

```bash
PYTHONPATH=src python -m unittest tests.test_digest.DigestMessageTests.test_renders_weekday_holiday_before_events
```

Local inspection without touching Telegram or publication state:

```bash
PYTHONPATH=src python -m telegrambot preview
```

CLI subcommands (see [`__main__.py`](src/telegrambot/__main__.py) for the full
list): `morning`/`run`, `update`, `refresh-current`, `preview`, `status`,
`listen`, `electricity`, `electricity-preview`,
`electricity-update-explanation`, `sync-municipal-events`,
`sync-agenda-events`, `prepare-event-translations`, `prepare-aemet`,
`monitor-updates`. Each `termux/*.sh` wrapper invokes exactly one of these; that
mapping is how to find which cron slot exercises a code path.

## Architecture

One Python package, `src/telegrambot`, standard library only plus `tzdata`. No
framework, no server, no scheduler inside the app.

**Everything is a one-shot process.** There is no resident loop except the
optional `listen` operator listener. Timing lives entirely in external Termux
cron (schedules documented in [README.md](README.md)). A code change that
introduces sleeping, polling, a background task, or a cache layer violates a
documented constraint — the recovery mechanism is always "the next scheduled
invocation retries".

### Layering

`__main__.py` resolves env/paths and dispatches → `morning.py` fans out source
adapters concurrently and swallows per-source failures → `digest.py` formats
deterministically → `delivery.py` guards publication against duplicates →
`telegram.py` sends. `models.py` holds the frozen dataclasses that are the only
things crossing the adapter/domain boundary; adapters must not leak
source-shaped payloads past themselves.

Adapters (one per approved official source): `aemet.py`, `safebeach.py`,
`agenda.py`, `municipal_agenda.py`, `todo_cultura.py`, `mayor.py`, `police.py`,
`electricity.py` (ESIOS). `holidays.py` is a reviewed in-code calendar, not a
request.

### The daily state machine

This is the part that requires reading several files at once. `state.py`
(`PublicationState`) holds one small atomic JSON file per workflow, guarded by
an `fcntl` lock via `state.exclusive_run()`. The morning digest is published
once at 07:30 and may be *replaced* exactly once later:

1. `prepare-*` commands pre-compute translations and one AEMET snapshot so the
   07:30 run makes no LLM call and can survive AEMET being down.
2. `morning` sends the digest and records its message ID.
3. `update` (10:10–10:40, seven attempts) polls SafeBeach; only a complete
   six-zone reading — or any valid reading on the final 10:40 attempt — is
   eligible. `_select_beach_for_update` in `__main__.py` keeps the best *whole*
   partial response as a candidate; separate attempts are never merged.
4. On an eligible beach reading or a verified Mayor-channel notice,
   `publish_update` sends the replacement **before** deleting the old message,
   then records the deletion. A failed delete returns `cleanup_failure` and the
   next invocation retries only the delete.
5. `monitor-updates` afterwards posts confirmed beach/warning changes as
   *replies* to the current digest, using `operational_updates.py`'s
   two-confirmation pending state.

Every string returned by these workflows (`"success"`, `"duplicate"`,
`"waiting"`, `"no_update"`, `"cleanup_failure"`, …) is load-bearing for the exit
code and for whether cron retries. Electricity is a fully separate workflow with
its own state file and lock and must not reach into digest internals.

### Fail-closed rules

- A failed optional source omits its section. It never blocks the digest and
  never becomes a plausible-looking default. Missing data is silence, not
  reassurance — see [docs/kb/02_Project_Principles.md](docs/kb/02_Project_Principles.md).
- Every outbound client pins an exact HTTPS host, an expected content type, a
  timeout, and a response-size cap (`API_HOST` / `REQUEST_TIMEOUT_SECONDS` /
  `RESPONSE_LIMIT_BYTES` constants). Copy that shape for any new transport.
- LLM use is narrow and validated by application code, never by the model:
  Gemini (`gemini.py`) primary, one pinned non-Google OpenRouter model
  (`openrouter.py`) as the single fallback. Approved tasks only — see
  [docs/kb/07_AI_Guidelines.md](docs/kb/07_AI_Guidelines.md). Do not add AI to
  weather, warnings, beach status, selection, formatting, or delivery.
- Errors carry stable `diagnostic_code` values that reach the operator; provider
  or source response text is never surfaced.

## Conventions

- User-facing output is **Russian**; timestamps and dates are `Europe/Madrid`.
  Expected digest strings live in `tests/test_digest.py` — wording changes are
  product changes and belong in `docs/kb/05_Features.md`.
- Tests are stdlib `unittest`, `IsolatedAsyncioTestCase` for async paths, with
  fixtures and `unittest.mock` patching of transports. No network in tests, no
  pytest, no third-party test dependency.
- Docstrings state the *invariant* a function protects, not what it does.
- Adding a runtime dependency requires passing the five-question decision test
  at the end of `docs/kb/04_Runtime_Constraints.md`.

## Deployment

CI (`.github/workflows/tests.yml`) runs the suite on every push and, on `main`
only, fast-forwards the `deploy` branch to the tested commit. `termux/deploy.sh`
pulls that branch at 04:00 on the phone, refuses dirty or non-fast-forward
checkouts, reruns the tests on-device, and rolls back on failure. So `main` is
the release trigger — a broken commit on `main` reaches the device.
