# ADR 0099: Hourly bounded AEMET CAP monitoring

- Status: Accepted
- Date: 2026-10-05
- Supersedes: the AEMET cadence and cross-lifecycle coupling portions of ADR 0031, plus ADR 0094's requirement to keep the old AEMET cadence unchanged

## Context

Production on 4 October 2026 exposed a blind spot in the existing three-times-
daily AEMET warning cadence. The 19:00 operational check observed no Guardamar
warning, while a later successful CAP read contained two yellow warnings for
the Guardamar warning zone with a 22:00-23:59 validity window. With no AEMET
check after 19:00, those warnings could expire before the next morning
snapshot and never become visible through the bot.

The AEMET CAP adapter itself remained healthy: the later read normalized the
same official zone and the existing deterministic renderer recognized the
warning labels. Increasing the whole weather collection cadence would add
unnecessary network work. Reusing the old operational windows directly would
also couple AEMET frequency to SafeBeach and CAMS/Meteosalud lifecycles.

## Decision

Keep AEMET operational monitoring as a short-lived Termux one-shot, but fetch
only the official CAP warning product once per hour from 07:51 through 23:51
Europe/Madrid.

The exact minute is deliberately independent of the existing operational
windows. SafeBeach keeps its established primary and confirmation minutes, and
CAMS/Meteosalud keep their existing recovery checkpoints. The managed Termux
cron block adds:

```cron
51 7-23 * * * /path/to/termux/monitor-updates.sh
```

The existing seasonal `:00/:05/:10` monitor rows remain because they continue
to own SafeBeach and the established environment checkpoints. The runtime
schedule therefore exposes three independent flags:

- `beach_phase` for SafeBeach collection/confirmation;
- `check_environment` for the existing CAMS/Meteosalud checkpoints;
- `check_aemet` only at `:51` from 07:00 through 23:00.

No additional daemon, scheduler, source, dependency, database, queue or raw CAP
archive is introduced.

## Warning state and delivery

The compact daily warning baseline remains the last successfully delivered
AEMET state.

Every scheduled AEMET checkpoint performs a fresh CAP read even when a prior
`warning_ready` value exists. A successful read recomputes the pending update
against that delivered baseline. This has three consequences:

1. a newer CAP can replace an undelivered older pending warning;
2. natural expiry can clear an undelivered pending warning silently;
3. an unavailable CAP source preserves state but does not send a potentially
   stale pending warning until a fresh successful CAP observation is available.

Unknown warning labels remain fail-closed. They may remain pending and be
rechecked on later hourly CAP observations, but they do not block future CAP
fetches or SafeBeach work.

AEMET delivery and SafeBeach delivery are independent. A pending warning does
not block a SafeBeach primary sample, and a pending SafeBeach confirmation does
not block an AEMET warning reply. A successful AEMET delivery commits only the
warning baseline; it must not mutate `beach_ready`.

The state schema remains version 1 and requires no migration.

## Resource and failure bounds

Each AEMET operational run requests only the existing CAP product through the
existing bounded adapter. The adapter keeps its current two-attempt optional-
product recovery, 15-second request timeout, bounded response limits and
bounded retry delay.

The process remains one-shot and normally exits after one small metadata/data
pair plus deterministic normalization. SafeBeach, CAMS and Meteosalud request
counts are unchanged by this decision.

The overnight interval after 23:51 and before the prepared 07:15 snapshot is
an explicit product boundary. Extending warning delivery across midnight would
require a separate decision about anchors, rollover and nighttime publication;
it is not added here.

## Cron installation safety

Because this change modifies the production crontab, the operational monitor
installer must fail closed when the existing crontab cannot be read and must
reject malformed or duplicate managed-block markers. A genuinely absent
crontab remains a valid empty starting state. Re-running the installer must be
idempotent and preserve unrelated jobs.

## Consequences

- Short-lived evening AEMET warnings can be observed with at most roughly one
  hour of scheduled delay during the 07:51-23:51 monitoring window.
- AEMET no longer inherits SafeBeach seasonal timing.
- Increasing AEMET frequency does not increase CAMS/Meteosalud or SafeBeach
  frequency.
- Pending warning and beach state cannot suppress the other lifecycle.
- Runtime and persistent-state complexity remain essentially unchanged.

## Acceptance criteria

- `check_aemet` is true only at minute 51 from 07:51 through 23:51.
- Existing SafeBeach primary/confirmation times are unchanged.
- Existing CAMS/Meteosalud checkpoints are unchanged.
- AEMET fetches continue while `warning_ready` exists.
- A fresh successful CAP observation replaces or clears stale pending warning
  state before delivery.
- A CAP fetch failure preserves pending/baseline state and sends no stale
  pending warning on that invocation.
- AEMET delivery never clears or commits `beach_ready`.
- SafeBeach primary collection is not blocked by `warning_ready`.
- The cron installer is idempotent, preserves unrelated jobs, accepts a normal
  empty crontab and rejects read failures or malformed managed markers.
- No state migration, daemon, new dependency, source, AI call or raw-response
  persistence is introduced.
