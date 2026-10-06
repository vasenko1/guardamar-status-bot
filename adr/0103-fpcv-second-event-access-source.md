# ADR 0103: FPCV as the second event-access source

- Status: Accepted
- Date: 2026-10-06
- Implementation: Sports Slice G; production rollout pending
- Refines: ADR 0092, ADR 0100, ADR 0101
- Research: `research/2026-10-05-sports-event-implementation-plan.md`

## Context

ADR 0101 already normalizes the exact FPCV convocatoria for the reviewed
Guardamar provincial fishing event during the existing 05:10 Pesca CV source
refresh. That normalized detail contains the event date, beach venue,
programme, club-mediated registration deadline and participant fee. Event
Access must reuse that observation rather than fetch or parse the PDF again.

The access lifecycle also requires a stable source-owned record identity.
Mutable date, venue, PDF URL, content hash and the existing date-based
`join_key` cannot own a long-lived Telegram root. The official convocatoria
itself exposes `Número 43/26`, which is the appropriate identity fact for the
reviewed event.

The existing `state/pesca_cv_details.json` version 1 predates this identity
field and is a regenerable source snapshot rather than lifecycle state.

## Decision

- Extract the source-assigned convocatoria number inside the existing bounded
  FPCV PDF parser. Require the two-digit convocatoria year to match the event
  year and fail closed when the marker is absent or inconsistent.
- Evolve only `state/pesca_cv_details.json` to source-snapshot version 2.
  The reader accepts legacy v1 records without identity; the writer emits v2.
  A legacy same-document record is re-extracted once on the next ordinary
  source refresh so the stable identity can be populated. No EventAccess state
  migration is involved.
- A legacy v1 detail remains valid for ordinary fishing presentation but is
  not actionable for proactive Event Access until a proven source ID exists.
- Use `fpcv:convocatoria:<number>-<year>`, for example
  `fpcv:convocatoria:43-26`, as the EventAccess `record_id`. Date, place,
  schedule, action URL and content hash never participate in that identity.
- Project the normalized record as access kind `registration` with one
  `club-registration` option. The official wording is represented as
  registration through the participant's fishing club; do not invent a direct
  public self-registration link.
- Keep the source-proven participant amount as presentation detail
  (`Взнос участника`), not as a spectator ticket price.
- Keep the existing 36-hour horizon only for ordinary fishing enrichment.
  Proactive FPCV EventAccess requires an identity-safe observation from the same
  Europe/Madrid local date and rejects future timestamps. A failed current-day
  details refresh may preserve last-good enrichment bytes, but yesterday's
  snapshot cannot make a current open/closing/cancelled access claim.
- Add FPCV to the existing explicit local-only EventAccess loader next to
  CONVEGA. Each source owns its freshness and is omitted independently.
  Deterministic ordering and the single global uncertain-delivery slot remain
  unchanged.
- The EventAccess runner performs no FPCV HTTP or PDF work. Network collection,
  SHA checking and `pdftotext` remain only in the existing Pesca CV refresh.
- Add no provider registry, dynamic discovery, ownership framework, daemon,
  database, queue, per-sport state or new cron.
- Move the two existing shared EventAccess checkpoints from 12:47/13:47 to
  10:47/11:47 Europe/Madrid. The live production crontab/runtime probe showed
  the SafeBeach edit window ends by 10:40, resident-news runs at 11:11,
  operational monitoring runs at 10:51/11:51 and earthquake checks at
  10:55/11:55. The selected :47 slots avoid those jobs, give 73 and 13 minutes
  of lead time before a reviewed 12:00 deadline, preserve the one-hour
  primary/recovery spacing, and keep the recovery inside CONVEGA's <=90-minute
  access-freshness window so it normally reuses the primary snapshot. Do not
  add a third sports-specific checkpoint.

## Failure and rollback behaviour

The strict base calendar `state/pesca_cv_events.json` is unchanged, so a
details problem cannot remove the underlying accepted fishing event.

Before the first v2 details refresh, new code reads the existing v1 file and
simply withholds FPCV access because no stable source identity is present.
After v2 has been written, rolling code back to the previous strict v1 reader
causes only FPCV detail enrichment to be ignored until that older source
refresher runs again and rewrites its own compatible snapshot. The base fishing
calendar remains available throughout. EventAccess v3 lifecycle state is not
downgraded by this source rollback.

If a changed PDF is fetched but its identity or semantic contract no longer
parses, the changed record is withheld instead of serving the previous access
truth. A cancelled index row may carry forward a previously proven
convocatoria identity for the same source join; without such proof it cannot
create a new access root.

## Consequences

FPCV becomes the second enabled EventAccess source without creating a second
sports subsystem. One official source observation feeds both ordinary event
presentation and proactive access, while the persistent Telegram lifecycle
continues to own only delivery history and material correction context.

The next source can reuse the explicit aggregator shape only after proving its
own stable identity, action contract, correction semantics and freshness.
