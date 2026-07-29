# ADR 0008: One-shot morning execution

- Status: Partially superseded by ADR 0021
- Date: 2026-07-27
- Supersedes: ADR 0001 scheduling/state rules and ADR 0005

## Context

The Morning Digest is published once per day. A resident process, internal
scheduler, Telegram update polling, background collectors, and cache
synchronization provide no proportional value on a weak Android device.

## Decision

- Use an external Termux scheduling mechanism to invoke the application at
  `07:30` in `Europe/Madrid`.
- During that invocation, collect every implemented official source directly
  once, normalize, build, publish, persist success, and exit.
- Keep no periodic collector, watcher, synchronization job, or webhook.
- The original one-field state rule is superseded by ADR 0021.
- Hold an empty local lock file during the run to prevent overlapping
  processes; the lock contains no source or publication state.
- Skip collection when the current local date is already confirmed successful.
- Write no publication state after collection or Telegram failure.
- Keep bounded Telegram send retries and the existing critical/optional source
  failure policy.
- Keep CLI `preview` and `status` for local operation. ADR 0010 later permits
  one isolated private preview listener without changing this publication
  flow.
- Do not cache raw, normalized, municipal, or event data.

## Consequences

- The application consumes no CPU, memory, battery, or network between runs.
- Deployment owns the 07:30 trigger; the application no longer catches up or
  waits for tomorrow.
- A failed run may be invoked again because it has no success record.
- Existing confirmed-success state can be read once during migration; the next
  success rewrites the file to the new one-field schema.
- Telegram `sendMessage` has no idempotency key. If Telegram accepts a message
  but its response is lost before state is written, exact outcome cannot be
  proven from success-only local state.

## Alternatives considered

- Keep the resident scheduler and publication long polling: rejected as
  unnecessary idle runtime. ADR 0010 permits long polling only for explicit
  operator previews.
- Cache municipal responses: rejected because the digest must use fresh
  morning data and stale municipal notices are unsafe.
- Store attempt and failure status: rejected by the new minimal state contract.
