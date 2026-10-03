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

However, the code is **not yet ready** for multi-source event-access rollout.
Several concrete gaps must be resolved or probed first. None requires a heavy
framework.

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

### 7. State v1 needs one deterministic migration

Do not create several state versions during the same rollout.

Recommended next schema is one new version containing:

- semantic record/option baseline;
- announced record IDs;
- trigger IDs;
- root message metadata;
- one uncertain outbound reservation.

Migrate every valid v1 `RegistrationRecord` as:

- `access_kind="registration"`;
- one deterministic single option (for example source-specific/default);
- existing explicit/unknown evidence preserved;
- no invented root message ID.

Current production baseline is silent, so migration itself must not publish.

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
3. one bounded atomic state file stores semantic baseline, roots, triggers and
   one uncertain reservation;
4. explicit source calls provide partial-failure behavior and per-source
   freshness;
5. one record-at-a-time loop performs reserve -> send -> commit;
6. root renderer uses photo only when one-message completeness fits;
7. later updates use existing strict text replies.

Keep all network collection outside the semantic planner.

## Required production probe before code

The next probe must measure/verify, for each accepted source:

- stable parent record identity;
- stable option/session identity;
- current/future access evidence;
- not-yet-open/open/full/sold-out/closed behavior where observable;
- unique poster availability;
- current presentation completeness;
- source publication/modified time;
- translation readiness;
- event lead time vs current source horizon;
- simultaneous eligible root count.

Do not write multi-source runtime code until those facts are collected.
