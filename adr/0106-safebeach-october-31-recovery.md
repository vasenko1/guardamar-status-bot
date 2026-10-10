# ADR 0106: Keep SafeBeach through 31 October and close the October late-start gap

- Status: Accepted
- Date: 2026-10-10
- Supersedes: ADR 0094 for the annual SafeBeach query window and October later-day cadence

## Context

ADR 0094 extended the internal SafeBeach request guard through 15 October after
a current active record was observed on 3 October. New evidence shows that this
boundary is still too early.

On 4 October 2026, EFE quoted Guardamar mayor José Luis Sáez stating that the
municipal salvamento y socorrismo service remains active through 31 October on
Playa Centro and La Roqueta. This is sufficient to move the internal request
guard through the end of October; it is not used as a runtime beach-status
source.

A read-only production investigation on 10 October also exposed a later-day
coverage gap. The 10:10-10:40 update cycle returned no eligible active
SafeBeach record, and the 12:00 operational checkpoint did not create a pending
candidate. At 13:17 Europe/Madrid the same official SafeBeach page contained a
current active Centre / Babilònia record with:

- `hasActividad=true`;
- `serviceEnded=false`;
- yellow flag;
- source update time `10:00`;
- current local page date 2026-10-10.

The production normalizer accepted that record and `is_current_status()`
returned true, but no daily beach root existed because the next October primary
checkpoint was not until 14:00. A separate 6 October observation showed the
Centre record already marked `serviceEnded=true` with `hora=14:00` later
that afternoon. A two-hour 12:00-14:00 gap can therefore delay the first useful
status and can race the end of a short October service window.

The fix must remain bounded, one-shot and independent from AEMET, CAMS,
Meteosalud and Mayor-channel schedules.

## Decision

- Allow scheduled SafeBeach requests from 1 June through 31 October,
  inclusive.
- From 1 November through 31 May, scheduled update and operational-monitor
  invocations make no SafeBeach request.
- Keep the existing 10:10-10:40 five-minute initial root lifecycle unchanged.
- Keep the normal October later-day primary windows at 12:00, 14:00, 16:00 and
  18:00.
- Add two October SafeBeach-only initial-recovery primary checkpoints at
  13:00 and 13:30. They perform a SafeBeach HTTP request only while today's
  beach root still lacks a confirmed SafeBeach status. Their confirmation
  invocations are 13:05/13:10 and 13:35/13:40.
- Confirmation invocations perform a SafeBeach HTTP request only while a
  candidate is pending, exactly like the existing operational state machine.
- The added 13:00/13:30 recovery checkpoints must not add CAMS, Meteosalud,
  AEMET or Mayor-channel work.
- Preserve the environment and Mayor-channel request budgets that existed
  before this change. Extending SafeBeach from 16 through 31 October must not
  extend the old SafeBeach-linked CAMS/Meteosalud overlap or the 10:10-10:40
  Mayor bathing-notice sidecar. On those newly covered dates, environment
  recovery remains on its pre-existing 11:00/15:00/19:00 checkpoints and the
  initial update cycle queries SafeBeach without adding Mayor-page reads.
- Keep all current-date, timestamp, known-beach, `hasActividad=true`,
  `serviceEnded=false`, flag-consistency and fail-closed validation rules
  unchanged.
- Preserve the `initial` marker when a first late status changes between
  phase one and phase two and therefore rolls to phase three; two matching
  observations of the new state must still be able to create the first root.
- A successful SafeBeach fetch that contains no eligible current status is
  logged explicitly; a successful current result logs the number of normalized
  current flag records. Source errors keep their existing diagnostic codes.
- Do not add season discovery, a daemon, sleeping retries, a browser, raw
  response storage, new persistent state or a dependency.

## Consequences

- The fixed guard now matches the confirmed 2026 October service horizon
  without pretending that every beach is staffed.
- October gains two additional scheduled initial-recovery opportunities, not
  two unconditional daily requests. Once a confirmed SafeBeach status exists,
  the 13:00/13:30 recovery windows make no SafeBeach HTTP request. The four
  associated confirmation cron invocations also make no request unless a
  candidate is pending.
- The 12:00-14:00 late-start blind spot is split by 13:00 and 13:30 recovery
  checkpoints while the existing bounded confirmation protection remains.
- AEMET, CAMS, Meteosalud and Mayor-channel request budgets remain unchanged;
  the SafeBeach season extension is explicitly decoupled from the frozen
  environment and Mayor sidecar cadences.
- No state migration is required.
- Winter and spring keep zero scheduled SafeBeach HTTP requests.

## Acceptance criteria

- 31 October 23:59 Europe/Madrid is inside the SafeBeach query window.
- 1 November 00:00 Europe/Madrid is outside it.
- October normal primary checks remain 12:00/14:00/16:00/18:00.
- 13:00 and 13:30 in October are additional initial-recovery phase-one
  checkpoints; +5 minutes is phase two and +10 minutes is phase three.
- Those recovery phases skip SafeBeach HTTP once the daily root already stores
  a confirmed SafeBeach status, but remain eligible for a Mayor-only root.
- The 13:00/13:30 recovery checkpoints have `check_environment=false` and
  `check_aemet=false`.
- On 15 October at 14:00 the legacy environment overlap is still present; on
  16-31 October at 12:00/14:00/16:00/18:00 the SafeBeach phase remains active
  while `check_environment=false`.
- No phase-two or phase-three SafeBeach HTTP request occurs without a pending
  candidate.
- The managed Termux cron block covers all of October and includes the two
  recovery confirmation groups.
- No SafeBeach request is made from 1 November through 31 May.
- Existing active/non-ended/current validation remains unchanged.

## Evidence

- EFE, 4 October 2026:
  `https://efe.com/comunidad-valenciana/2026-10-04/mueren-dos-jovenes-ahogados-en-una-playa-de-guardamar-de-segura-alicante/`
- Guardamar SafeBeach public page:
  `https://info.safebeach.es/guardamar-del-segura`
- Production read-only observations documented in
  `research/2026-10-10-safebeach-october-late-start-gap.md`.