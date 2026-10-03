# Event-access full architecture and code review

## Status

Full repository/design review completed 2026-10-03 against:

- deployed ADR 0089 runtime;
- accepted ADR 0090 threaded roots;
- accepted ADR 0091 event-access options;
- current `main` source adapters, translation preparation, Telegram transport,
  Termux scheduling and state patterns.

This review changes documentation/decision detail only. Runtime remains the
already device-validated ADR 0089 implementation.

## Overall conclusion

The target direction is sound and fits the project's Termux constraints.

No database, queue, daemon, generic event bus, browser, continuous polling,
media album system or second Event model is justified.

The implementation should remain one small source-projection + lifecycle
extension of the existing bot.

The production reconnaissance and final pre-implementation review later closed
the core gate. The findings below remain the historical code/design analysis,
while the controlling implementation refinements are now recorded in
`research/2026-10-03-event-access-final-preimplementation-review.md` and
ADRs 0090-0092.

The first runtime rollout is deliberately narrower than the full multi-source
target: event-access core + state v2 + CONVEGA only.

## Verified strengths to reuse

### Existing Event contract

The global `Event` presentation model already carries the useful resident
facts:

- ticket price/URL;
- registration URL/contact;
- capacity;
- access note;
- teaser/details;
- audience/duration/place;
- image URL.

Do not replace it.

### Existing source snapshots

Municipal, Agenda Guardamar, Library, AM Guardamar, FACV and CONVEGA already
persist bounded normalized state with timestamps/provenance appropriate to
their current responsibilities.

### Existing translation cache

The project already has a bounded atomic event-translation cache and dedicated
title/teaser translators.

### Existing Telegram transport

Current transport already provides:

- strict text replies using `reply_parameters` with
  `allow_sending_without_reply=false`;
- remote photo sends returning Telegram `message_id`;
- deterministic 1024-character photo-caption validation;
- ambiguous-send classification that treats timeout/network/invalid response
  structure as potentially delivered.

The current photo-result `INVALID-STRUCTURE` condition is classified as
ambiguous by `is_ambiguous_send_failure()`, so a missing/invalid successful
response must not be automatically resent.

### Existing crash-safety pattern

Persist-before-send uncertain delivery is the correct lightweight pattern and
should be retained.

## Critical implementation gaps

### 1. Future access candidates are not consistently translated

This is the largest presentation gap.

Current translation-item behavior:

- municipal: uses `_cached_current_events()`, therefore only events active
  today;
- Agenda Guardamar: explicitly filters to today's date;
- Library: explicitly filters to currently active/today;
- AM Guardamar: `_current_events()` only returns events active today;
- FACV: already prepares translations for usable future rows;
- CONVEGA: already prepares translations for future Guardamar records.

Therefore future ticket/registration/reservation roots from municipal, Agenda,
Library or AM Guardamar may fall back to Spanish even though the source was
collected in the morning.

**Decision:** do not add another translation engine. Extend the existing
translation-preparation items with only future actionable access candidates.

### 2. Stable parent identity is missing from key sources

Municipal `_source_event_key()` is currently
`(title, start_date, start_time)`; this is suitable for local transition
deduplication but not durable lifecycle identity because date/time corrections
change the key.

Municipal `session_source_key` proves a source session family but is not by
itself a durable event occurrence ID across all dates/corrections.

Agenda Guardamar already parses multiple session-specific ticket URLs from one
detail page, but its normalized snapshot loses the parent detail-page identity.

FACV current dedup identity is title + dates + place rather than a stable
tournament/article ID.

**Decision:** no lifecycle implementation for a source until production probes
identify a safe parent record ID and, where needed, safe option IDs.

### 3. Current source horizons are not suitable as one global access horizon

Reviewed code currently has materially different scopes:

- Library: 7 days;
- Agenda Guardamar: 45 days;
- AM Guardamar: 45 days;
- municipal programme/news candidates: roughly 44/45 days;
- CONVEGA: 370 days;
- FACV: provider-calendar bounded rather than one explicit day constant.

A seven-day Library horizon may be perfectly adequate for Morning but too short
for proactive reservations if its official page publishes further ahead.

**Decision:** keep horizons source-specific and change only from measured
first-party lead-time evidence.

### 4. Freshness is still globally CONVEGA-owned

The deployed notifier rejects the entire run based on the CONVEGA snapshot
timestamp and loads records only from CONVEGA.

A multi-source access run must preserve partial failure:

- stale CONVEGA must not suppress fresh municipal access;
- stale Library must not suppress fresh Agenda Guardamar access.

**Decision:** each source projection owns its snapshot timestamp/freshness.
The orchestrator consumes only fresh source batches and may still publish from
other fresh sources.

Do not create a dynamic plugin registry; call the small accepted source
projections explicitly.

### 5. V1 planner batching is incompatible with separate roots

Current `plan_registration_run()` computes notices for all records and one
candidate baseline containing all current records. This is correct while one
Telegram message contains all notices.

With ADR 0090, sending only root A and committing baseline B/C would suppress
unsent first roots B/C.

**Decision:** process event records one at a time in deterministic order.

Minimal algorithm:

```text
for record in deterministic eligible order:
    plan only that record against current persisted state

    if silent:
        commit its semantic observation
        continue

    persist one uncertain reservation
    send root/reply
    commit that record + trigger/root metadata
    continue
```

An ambiguous send stops the run at one well-defined reservation. Already
committed earlier records remain safe. Later records remain eligible.

This is a single-slot transactional-outbox pattern without a queue.

### 6. Option baseline must merge observations, not replace the option map

For a multi-session event, a source may temporarily omit one option.

Replacing prior `options` wholesale would falsely erase history and could
produce incorrect aggregate "all full/closed" conclusions.

**Decision:** update only observed option IDs; retain missing prior option
evidence until event-retention pruning. Disappearance stays silent.

### 7. State v1 needs one deterministic event-centric migration

Do not create several state versions during the same rollout.

The clean-sheet follow-up review recorded in ADR 0092 replaces the earlier
parallel global target collections with one bounded event-centric map:

```text
records[record_id] {
  semantic
  audience_known
  root?
  sent_triggers[]
}
uncertain?
```

Migrate every valid v1 `RegistrationRecord` as:

- `access_kind="registration"`;
- one deterministic single option (for example source-specific/default);
- existing explicit/unknown evidence preserved;
- legacy announced membership -> `audience_known`;
- that record's legacy triggers -> record-local `sent_triggers`;
- no invented root message ID.

Current production baseline is silent, so migration itself must not publish.
After the atomic migration, normal runtime supports only the new version.

### 8. First-known deadline still needs its own semantic

Current v1 `_change_notices()` labels
`None -> explicit registration_end_date` as `deadline-changed`.

For new municipal/FACV/Library sources, "deadline first became known" is common.

Add a separate notice kind before multi-source rollout.

### 9. Ticket/open evidence must stay source-specific

Current Agenda Guardamar ticket URLs are occurrence-specific and strongly
validated, but the code review alone does not prove that the link is absent
before sale starts or after sell-out.

Price alone is not open evidence.

Do not create a generic "ticket_url means open" rule until production probes
observe not-yet-open / open / sold-out behavior.

Keep source-specific URL allowlists instead of broadening
`event_urls.py` globally.

### 10. Root-card media fallback must stay atomic

Telegram currently supports a 1024-character photo caption and returns the
created Message on successful `sendPhoto`.

Preferred root transaction:

- if all material facts fit the bounded caption and safe poster exists -> one
  photo root;
- otherwise -> one complete text root;
- deterministic remote-media rejection -> safe text fallback in the same
  reserved root transaction;
- timeout/network/invalid success structure -> ambiguous, block automatic
  fallback/resend.

Do not implement a default two-message photo + overflow root transaction.

### 11. Exact opening times do not justify per-event timers

The existing 12:47/13:47 lifecycle can cross some exact opening boundaries, but
a source may state a later exact time.

Do not create per-event scheduled jobs/timers.

If access opens later that day, the rich root can state the exact future time.
A "now open" reply is sent only when a later normal source observation/run
positively confirms current availability.

This is consistent with the project's non-realtime design.

### 12. Simultaneous root volume is still unmeasured

Separate rich roots remain the correct UX/identity model.

Do not set a permanent arbitrary "3/5 per day" cap yet. The production probe
must count historical/current simultaneous eligible roots.

Implementation still needs structural bounds from accepted source record caps.
If a product-level send cap is later justified, unsent records must remain
eligible rather than being grouped.

## Data-model simplification

ADR 0091 originally placed `kind` on every AccessOption.

The code review recommends a simpler first schema:

```text
EventAccessRecord
  record_id
  source
  source_url
  access_kind        # registration | reservation | ticket
  event date/range
  current presentation facts (not persisted as semantic baseline)
  options[]

AccessOption
  option_id
  occurrence date/time or source label
  status             # unknown | open | full | closed
  action_url/contact
  optional opens/closes boundary
  until_full
  optional price presentation
```

All options of one root share one access kind in v1.

This covers every reviewed source while avoiding polymorphic option rendering.
If a real first-party event later mixes genuinely different access kinds under
one parent, review that source then instead of generalizing now.

Several contact methods for one tournament remain one option.

## Presentation-state boundary

A separate persisted presentation database is unnecessary.

One immutable current `EventAccessRecord` may carry presentation facts such as
poster/place/description for rendering, while the baseline serializer persists
only semantic lifecycle fields.

Therefore:

- poster change is not a lifecycle change;
- teaser translation change is not a lifecycle change;
- place/title presentation correction does not by itself alter option status;
- event date/time corrections may be persisted only where they are part of
  lifecycle identity/correction semantics.

This is simpler than maintaining a second persistent presentation state.

## Translation pattern

Reuse the existing 06:00/06:30/07:00 preparation workflow.

Each source's translation-item function should include:

1. the existing current-day items;
2. future events only when that source projects actionable/future-boundary
   EventAccessRecords.

Use the existing teaser translator for descriptive text categories. Do not send
Library or access-card prose through the title translator merely because the
cache accepts arbitrary source keys.

Do not translate every future event merely because it is in a 45-day catalog.

If a future late pre-12:47 source refresh is later justified, translation of
new candidates belongs to that bounded preparation phase, not inside Telegram
delivery.

## Scheduling review

Keep initially:

- existing source refreshes around 05:10/05:30;
- existing translation preparation;
- 12:47 access lifecycle;
- 13:47 recovery.

No second source sync is justified yet.

The required timing probe must compare source publication/modified times against
the 05:10/05:30 observations. Add one lightweight pre-12:47 refresh only when
real missed same-day access announcements justify it.

## Source-specific review

### Municipal/Turismo

Strengths:

- already stores registration/contact/ticket/capacity/image facts;
- raw snapshot contains future programme records beyond today's renderer;
- source session-family logic already exists.

Gaps:

- current translation items are today-only;
- current transition key is date/time-based;
- session-family key is not yet proven lifecycle-stable;
- exact per-session action URLs/status behavior needs live evidence.

### Agenda Guardamar

Strengths:

- bounded 45-day detail catalog;
- parses multiple session ticket URLs from one parent page;
- strict occurrence URL validation.

Gaps:

- parent detail identity is discarded in snapshot;
- translations are today-only;
- no image retained for access roots yet;
- sale-open/sold-out meaning of the ticket link needs live evidence.

### Library

Strengths:

- stable first-party detail URL retained;
- changed detail pages already fetched;
- teaser cache exists.

Gaps:

- seven-day horizon may hide earlier reservations;
- translation items are today/active only;
- first-party reservation/action extraction not yet implemented;
- current generic teaser preparation should use the descriptive translator.

### FACV

Strengths:

- translation items already include future usable tournament rows;
- official articles have rich registration facts.

Gaps:

- current row identity is title/date/place based;
- stable tournament/detail ID and current-action semantics need probe;
- presentation image/article facts are not retained in current normalized row.

### AM Guardamar

Strengths:

- stable WordPress post ID;
- modified timestamp;
- official featured image;
- 45-day candidate horizon.

Gaps:

- translation items are active-today only;
- one post may need a reviewed child occurrence identity if it contains several
  public events;
- ticket/reservation extraction quality needs probe.

### CONVEGA

Already provides stable source IDs and future translation items.

Its current registration projection should become the migration/reference
single-option EventAccessRecord.

## Explicit anti-patterns rejected

Do not introduce:

- one engine for registration plus a second engine for tickets;
- a universal "scan merged Event[]" filter;
- fuzzy title grouping for sessions;
- date/time-only lifecycle IDs when a better source ID exists;
- wholesale replacement of prior option baselines;
- "ticket URL exists => sale open" globally;
- price-change monitoring in v1;
- inline-button editing/state in v1;
- album delivery;
- multi-message root transactions by default;
- per-event timers;
- continuous polling;
- a generic plugin/source registry;
- database, Redis, message broker or worker queue;
- browser/Playwright;
- AI classification inside the send path;
- translation of every future catalogue item.

## Adjacent but intentionally deferred

### Event cancellation

An explicit cancellation after residents have been told about access is highly
valuable, but adding cancellation now would broaden the feature into a general
event-status lifecycle before source contracts are measured.

Keep date/time corrections already accepted by ADR 0090. During production
probes, record whether candidate sources expose explicit cancellation in the
same stable identity. Add one evidence-backed cancellation transition later if
it is common/reliable.

### Price changes

Price stays presentation-only in v1.

## Minimum implementation shape after probes

No framework is required.

Recommended code shape:

1. source adapters expose explicit small event-access projections from their
   existing snapshots;
2. one access-notification module owns common validation/planning/rendering;
3. one bounded atomic state file stores event-centric `records[record_id]`
   entries plus one uncertain reservation;
4. explicit source calls provide partial-failure behavior and per-source
   freshness;
5. one record-at-a-time loop performs reserve -> send -> commit;
6. root renderer uses photo only when one-message completeness fits;
7. later updates use existing strict text replies.

Keep all network collection outside the semantic planner.

## Production probe status

The required read-only production probe was completed on 2026-10-03 and is
recorded in
`research/2026-10-03-event-access-production-recon.md`.

It opened the **core + CONVEGA** implementation gate while keeping every other
source capability-gated.

The final pre-implementation audit then tightened migration/rollback,
future-opening transitions, missing-option semantics, trigger identity,
CONVEGA freshness and the text-only first rollout. Those refinements are
controlling over earlier conceptual examples in this file.


## Final consistency findings

### 13. Cross-source duplicate roots need explicit ownership

The same real event may appear through Municipal/Turismo, Agenda Guardamar and,
for music events, AM Guardamar.

A naive multi-source orchestrator would create duplicate Telegram roots even
though each individual source record is valid.

Do not add a generic cross-source entity-resolution layer.

Instead, every accepted source projection must define an access-ownership rule.
When a municipal source delegates ticket purchase to Agenda Guardamar, the
Agenda occurrence should own that ticket lifecycle once the exact delegated
action/occurrence relationship is proven. Municipal data may enrich the card
only through a deterministic exact join.

Registration/reservation actions owned directly by Municipal, FACV, Library or
CONVEGA remain with those adapters.

The production probe must count overlaps and delegated URLs so those ownership
rules are evidence-backed.

### 14. Multi-option triggers must include option identity

The deployed trigger key is record-level. That will collide when two slots of
one event share a registration deadline.

The access implementation needs option-scoped trigger IDs for option-specific
opening/closing/deadline facts, e.g.

`kind:record_id:option_id:boundary`.

No additional trigger store is required; the existing bounded trigger list can
keep these keys.

### 15. Migration must not reinterpret a legacy uncertain send

A v1 state migration is simple only when `uncertain == null`.

The deployment gate should require the operator to resolve any legacy uncertain
registration delivery before switching schemas. This is safer and much smaller
than writing compatibility logic for an in-flight combined v1 publication.

Valid v1 records then migrate to one registration-kind access record with one
deterministic default option. Existing `announced_record_ids` remain audience
knowledge even though no root ID exists.

If a migrated announced record later needs a publication before a root exists,
create one self-contained replacement/current-state root and store its message
ID. Do not emit an orphan reply and do not mark it unannounced.

### 16. Avoid cosmetic runtime renames in the first rollout

The external cron/wrapper/state names currently contain "registration".

Renaming shell wrappers, environment variables and production state paths at
the same time as the state/schema/source expansion adds deployment churn with no
resident value.

Keep the existing cron/wrapper/state path names for the first event-access
rollout unless a rename is required for correctness. Internal new types and
documentation may use EventAccess terminology.

A later cleanup rename is optional and should not be coupled to the functional
migration.

### 17. Action-link corrections are useful but not a v1 root-edit system

If an already-open option's validated URL/contact changes, a concise threaded
reply with the corrected action is useful.

Do not introduce automatic root-message editing in v1 merely to keep old links
perfectly current. Root edits create another delivery/edit state path and are
not required for lifecycle correctness.

If real source probes show frequent action-link churn, revisit idempotent
known-root edits using the already existing Telegram edit transport.

### 18. Photo roots must opt into normal notifications

The existing `send_photo_url()` helper defaults to
`disable_notification=True`.

That default is correct for some current media flows but would silently change
the resident semantics of event-access alerts if reused without an explicit
argument.

**Decision:** root photo sends must pass `disable_notification=False`
explicitly. Keep this in the root-delivery unit tests.

### 19. Generic access needs offline action text

The deployed registration model only has URL/contact actions.

Official municipal access can instead be actionable through a physical point:
for example ticket sales or invitation pickup at Casa de Cultura during a
published campaign window.

Do not misuse a "contact" field for this.

**Decision:** the generic access option uses one optional validated
`action_url` plus optional source-backed `action_text`. The latter may
contain phone/email/WhatsApp instructions or an in-person box-office/desk
instruction.

An option may be current-open when either action form is positively proven by
the source contract.

### 20. Daily service hours are not lifecycle status

A physical ticket office may have recurring daily opening hours within a
multi-day sale campaign.

Treating every desk closing/reopening as `closed/open` would generate noise
and require a recurrent scheduler.

**Decision:** lifecycle status describes the access campaign, not whether the
physical counter is open at this minute. Recurring office hours stay in
presentation/action text. Only source-backed campaign boundaries drive
opening/closing lifecycle transitions.

### 21. Reuse one pure source projection for lifecycle and translation selection

Future rich-card translation must not implement a second independent
"actionable candidate" classifier.

**Decision:** each accepted source exposes one small deterministic access
projection from its existing normalized snapshot. Both:

- the access orchestrator; and
- that source's translation-item preparation

consume the same projected records.

This prevents translation eligibility from drifting away from publication
eligibility and keeps source parsing in one place.

The projection is pure/local-state work. Network access remains in the existing
source refresh layer.

### 22. Ownership cannot silently change after a root exists

Cross-source duplicate prevention already requires explicit ownership.

One more invariant is needed: once a source-owned record has created a Telegram
root, later discovery of another official source must not silently switch owner
and create a second record/root.

Secondary-source facts may enrich/confirm the existing owner only through an
already reviewed deterministic join. If the join cannot prove continuity,
prefer the existing root and suppress the competing projection rather than
perform an implicit owner migration.

### 23. Replace the global 512-trigger FIFO with record-local bounds

The deployed v1 state caps one global `sent_triggers` list at 512.

Option-scoped triggers make that shape undesirable because unrelated events can
evict each other's still-relevant boundary history.

ADR 0092 therefore stores trigger history inside each event entry. The
production probe should measure maximum options/triggers per retained event and
set one conservative record-local bound. Do not add a trigger database or
unbounded history.

### 24. Complete event-source inventory

The actual Morning/Weekend event pipeline also includes Pesca CV,
blood-donation events, Mayor late events and static recurring rules.

"Every event passes through the access filter" therefore means every
**source-owned future event adapter is eligible to expose an access
projection**, not that every rendered Event must create one.

- Municipal/Turismo, Agenda, Library, AM, FACV, CONVEGA remain primary access
  candidates.
- Pesca CV is now confirmed as a real long-lead access source: the official
  17 October Guardamar convocatoria was issued 14 September and sets club
  registration through 13 October at 12:00. Project access from the exact
  federation detail/PDF, not from the calendar row alone.
- Blood donation keeps its dedicated donor workflow unless an official
  appointment/booking product requirement is separately accepted.
- Mayor same-day late-event recovery is not a long-lead access source.
- static recurring Event rules have no source-owned actionable-access lifecycle
  and therefore project nothing.

This keeps coverage complete without turning the merged Morning Event list into
a universal lifecycle input.

## Final implementation recommendation

After production probes, implement one narrow access module evolution rather
than a framework:

```text
CONVEGA normalized snapshot
        ↓
pure CONVEGA access projection
        ↓
access-specific freshness
        ↓
record-at-a-time planner
        ↓
single-slot uncertain reservation
        ↓
one text root or one strict text reply
```

No dynamic plugin registry is needed. A small explicit list/call sequence is
clearer and safer for the current source count.

## Clean-sheet state correction after live reconnaissance

A final clean-sheet comparison asked whether the target would have the same
persistent shape if one-root, multi-option and multi-source requirements had
been known before ADR 0089.

Answer: the source/projection/lifecycle boundaries remain correct, but the v1
parallel global state collections are historical baggage.

ADR 0092 therefore makes the event record the persistence/transaction unit.
This is a simplification, not a framework expansion: one atomic JSON file,
bounded `records[record_id]`, and one uncertain outbound slot.

The live 2026-10-03 reconnaissance and subsequent Termux probe are complete.
They confirmed that CONVEGA is the only source ready for the first runtime
rollout; Agenda Guardamar, Municipal/Turismo, Biblioteca, FACV, Pesca CV and AM
Guardamar remain capability-gated.

The final controlling review is
`research/2026-10-03-event-access-final-preimplementation-review.md`.
