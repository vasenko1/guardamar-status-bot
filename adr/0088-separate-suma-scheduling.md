# ADR 0088 — Separate 08:05 SUMA scheduling

Date: 2026-10-02
Status: Accepted

## Context

ADR 0077 deliberately embedded the lightweight SUMA check in the 07:30
Morning Digest process to avoid another scheduled invocation. Production use
showed a product downside: on an actual SUMA trigger date the tax reminder is
published immediately beside the Morning Digest, making two important messages
arrive together.

The phone now also runs several bounded one-shot jobs in the early morning,
including the separate monthly-digest collector every ten minutes. Moving SUMA
must therefore separate both resident-facing publication and device/network
work rather than merely choosing another round minute.

## Decision

Detach SUMA from the Morning Digest lifecycle.

- `telegrambot morning` no longer invokes SUMA in a `finally` block.
- Keep the existing strict `telegrambot suma` command and all existing
  `suma.py` source, trigger, state and delivery semantics unchanged.
- Add one small `termux/run-suma.sh` one-shot with its own bounded
  `state/suma.log`.
- Add one idempotent managed cron block at **08:05 Europe/Madrid**.
- Do not add jitter, a resident process, a second automatic retry, or a generic
  scheduler.
- Do not use the project-wide runtime lock for SUMA. The existing
  `SumaState.exclusive_run()` remains the duplicate-run guard; an exact-date
  reminder must not be silently skipped merely because an unrelated monitor
  owns the shared runtime lock.

08:05 is intentionally staggered from the known morning schedule. It is
35 minutes after the 07:30 Morning Digest and lies halfway between the
monthly-digest collector invocations at 08:00 and 08:10. The nearest regular
device work is therefore at least five minutes away. The next planned
resident-facing transport notification is 08:42.

## Reliability

This change does not increase or decrease the normal SUMA attempt count: the
previous design performed one daily check inside the 07:30 process; the new
design performs one daily check at 08:05.

Existing SUMA semantics remain authoritative:

- exact-date triggers are never replayed on later dates;
- a definite delivery failure rolls back the trigger key and remains manually
  retryable that same day;
- an ambiguous Telegram send keeps the trigger key to avoid duplication;
- first successful bootstrap remains silent;
- source disagreement or source failure remains fail-closed.

A second scheduled retry is intentionally not added. It would add routine
source traffic and new scheduling collisions without changing the accepted
exact-date/fail-closed product model.

## Consequences

- Morning Digest and SUMA failures are isolated from each other.
- Important tax reminders no longer appear immediately beside the 07:30
  briefing.
- The weak Android device receives a more even early-morning workload.
- One additional lightweight external cron row replaces the previous embedded
  call, without adding a daemon, queue, database, dependency or background
  scheduler.
- ADR 0077 remains authoritative for SUMA sources, trigger semantics, state and
  delivery behavior; only its scheduling decision is superseded.
