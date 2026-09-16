# 0070: Publish semantic sports changes from accepted Sporttia state

- Status: Accepted
- Date: 2026-09-17

## Context

The linked guide already reads the municipal Sporttia centre page once per local day, normalizes the supported recurring sports, retains unexpired last-good rows, and reconciles durable Telegram cards. Residents can benefit from timely changes such as a newly opened registration window, a new group or season, and changed schedule/venue/audience/participation requirements.

Public `sendMessage` is an irreversible side effect. It must not turn raw HTML churn, source outages, deployment rollout, or ambiguous Telegram responses into duplicate or misleading public posts. The phone remains a low-power Termux host and does not need another poller, cron entry, browser, database, or notification framework.

## Decision

Sports notifications reuse the existing 16:30 `sync-guide.sh` invocation and the already accepted normalized Sporttia snapshot. The guide sync runs first; a second short Python one-shot then reads `state/guide.json` and `state/pinned_guide.json`. It performs no Sporttia or other source request.

Notification state is separate at `state/sports_notifications.json` (overridable with `SPORTS_NOTIFICATION_STATE_PATH`). It stores only the previous accepted Sporttia baseline, previously observed activity keys, one pending notification, compact date-trigger dedupe identifiers, launch-overview completion, delivery state, and the last Telegram message ID.

The first accepted observation is a silent semantic baseline. If that snapshot was observed on the current local date and explicit `NUEVAS INSCRIPCIONES` windows are already open, one deliberate launch overview may be published. It says that registration is currently open and never describes pre-existing activities as newly discovered. If the available snapshot is stale, launch output waits for a fresh accepted observation.

After the launch baseline, public semantic changes are limited to:

- a genuinely new supported activity;
- a new group in an existing activity;
- a new season;
- changed explicit registration windows;
- changed schedule, venue, audience/age or season dates;
- changed normalized participation conditions;
- appearance/removal of explicit `hasta completar` wording;
- start of an explicit registration window;
- one deadline reminder exactly three local calendar days before an explicit registration end date.

Date-triggered notices are evaluated only from a Sporttia snapshot observed on the same Europe/Madrid calendar date. They never use stale last-good data after a source failure. Opening/deadline dedupe identifiers are remembered only after successful Telegram delivery.

Row ordering, raw HTML changes, generic `Abierta/Cerrada`, occupancy/capacity, source failure, and disappearance from the Sporttia open-registration surface do not create notifications. The existing Sporttia merge contract therefore remains unchanged.

Multiple material changes from one daily observation are batched into one calm Telegram message and link to the already-reconciled activity cards. No per-activity Telegram message is created for a change.

Before `sendMessage`, delivery state is atomically persisted as `uncertain`, because Telegram provides no idempotency key. HTTP 429 is an explicit rejection and restores `idle` while retaining pending work for a safe retry. Any ambiguous failure leaves `uncertain` and disables automatic resend until the operator inspects Telegram/state. On success, pending work is cleared and date-trigger/launch dedupe state is committed.

A sports-notification failure does not undo or block an already successful guide reconciliation. `sync-guide.sh` logs the deferred notification run and still completes the guide job. This isolates the irreversible public side effect from the recoverable linked-guide update while preserving one cron schedule.

## Consequences

- No new source calls, polling interval, cron entry, resident process, dependency, database, browser, or generic notification engine is added.
- The production source contract remains ADR 0069: one bounded Sporttia centre-page GET at most once per local day.
- A second short Python process runs only after the daily guide sync and reads small local JSON files; this cost is negligible on the Termux host.
- Residents get evidence-bounded, batched updates instead of source-level noise.
- A genuinely ambiguous Telegram send requires operator inspection before sports notifications resume; guide reconciliation continues normally.
- Registration deadline policy is deterministic: exactly one reminder three days before the explicit end date, provided that day has a fresh accepted Sporttia observation.

## Alternatives considered

- **Send directly inside `guide.py`.** Rejected because the irreversible notification side effect would enlarge the guide orchestrator and couple its failure path to linked-message reconciliation.
- **Add another cron/poller for registration changes.** Rejected because the existing daily Sporttia observation already supplies the required facts.
- **Reuse/generalize `transport_notifications.py` into a notification framework.** Rejected as unnecessary abstraction; only its proven baseline/pending/uncertain invariants are copied.
- **Notify on row disappearance or `Abierta/Cerrada`.** Rejected because the Sporttia page is an open-registration surface and those signals do not prove cancellation, availability, or free capacity.
