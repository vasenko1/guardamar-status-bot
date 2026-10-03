# One-off registration publication timing, synchronization and architecture review

## Status

Research-only design review completed on 2026-10-03 after ADR 0089 and ADR 0090.

No runtime code, cron, state schema or Telegram behavior is changed by this
research.

The review covers:

- when a registration should first become publicly visible;
- whether explicit future opening dates should generate advance/current-open
  notices;
- whether existing event source synchronization is sufficient;
- whether simultaneous registrations should be grouped;
- how rich event-card roots and threaded lifecycle replies affect architecture;
- current gaps/bugs/overengineering risks before implementation.

## Current accepted baseline

ADR 0089 is deployed and already supports:

- source-owned one-off registration identity;
- `unknown/open/full/closed`;
- first-seen current `open` publication;
- optional registration start/end boundaries;
- tomorrow/same-day boundary notices;
- unknown preserving last explicit status;
- crash-safe uncertain delivery;
- 12:47 normal + 13:47 recovery.

ADR 0090 is accepted but not yet implemented:

- one `record_id` owns one Telegram root message;
- the first useful registration publication is a rich event card;
- later lifecycle changes reply strictly to that root;
- cross-event batching is retired;
- root Telegram `message_id` becomes bounded delivery metadata;
- ambiguous root-send recovery requires the verified root message ID.

The rich-card research additionally requires:

- event-specific official image when safe/unique;
- Russian title and concise translated description;
- date/time/place and material event facts;
- registration action/contact;
- deadline/capacity/participation requirements when known.

## Publication timing decision model

There are two independent concepts:

1. **source observation time** — when the bot learns a fact;
2. **registration boundary time** — when the source says registration opens or
   closes.

Never replace a missing registration boundary with observation time.

### Case A — registration is already open when first observed

If the accepted source positively proves residents can register now, publish at
the next one-off registration lifecycle run.

This applies even when:

- registration start date is unknown;
- registration end date is unknown;
- the event itself is weeks or months away.

Do not impose a generic 7/14/30-day event horizon merely to delay an already
actionable registration.

Source-specific catalogue horizons remain bounded for runtime safety, but
current `open` is itself the user-relevance trigger.

### Case B — explicit future registration start exists

If the source says registration starts in the future, do not publish a rich
root immediately just because that future boundary was discovered.

Recommended default:

- store the future boundary silently;
- on the day before the published opening date, create the rich event root:
  `Завтра открывается регистрация`;
- if an exact opening time is known, include it;
- on the opening day, send a concise reply only when registration is positively
  current/open or the actionable form/contact becomes usable;
- if the day-before root was missed, current-open may create the root directly.

This keeps the useful advance warning already present in ADR 0089 without
creating duplicate event promotions weeks before residents can act.

### Case C — explicit future opening discovered only one day or hours before

The same boundary logic applies naturally:

- tomorrow -> rich root `Завтра открывается...`;
- today before exact time -> rich root `Сегодня в HH:MM откроется...`;
- current open -> rich root `Идёт запись` when no prior root exists.

### Case D — one-day registration window

Prefer the existing one-day semantics:

- day before -> rich root `Регистрация только завтра`;
- on the day, a concise current-open reply is eligible when the action is
  actually usable;
- avoid redundant same-day close unless it is early/unexpected or otherwise
  adds material information.

### Case E — registration is already open and a deadline is known

Create the rich root immediately and include the deadline in that root.

Do not generate a second same-run deadline message merely because the deadline
is tomorrow. The root absorbs all material facts already known.

Later closing reminders remain eligible according to lifecycle rules.

### Case F — deadline first becomes known after open was announced

This is not a deadline revision.

Use a distinct semantic such as:

`Появился срок регистрации`

Only use `Изменился срок регистрации` when a previously explicit deadline
really changed.

### Why not notify immediately about a far-future opening date?

An immediate post such as `Регистрация откроется через 24 дня` produces a
second event promotion before residents can act, then another opening notice,
then later deadline/full/closed replies.

The day-before root is a simpler default:

- high practical value;
- low noise;
- no arbitrary multi-week reminder horizon;
- preserves one clear event root;
- avoids a generic reminder scheduler.

If later product evidence shows that a specific source/category requires
longer preparation (documents, authorization, travel booking), that should be a
source/category-specific rule, not a global generic reminder ladder.

## Synchronization inventory

### Current morning event collection

The existing 05:10 `sync-municipal-events.sh` one-shot sequentially refreshes:

- municipal/Turismo event catalogue;
- Biblioteca agenda;
- AM Guardamar;
- FACV Guardamar chess rows;
- Pesca CV event facts.

Agenda Guardamar has a separate 05:30 refresh.

This already gives one same-day event observation before publication.

### Current translation preparation

Existing event translation preparation runs before Morning publication
(documented at 06:00 / 06:30 / 07:00) and consumes local snapshots for:

- municipal events;
- Agenda Guardamar;
- library;
- AM Guardamar;
- FACV;
- Pesca CV;
- CONVEGA when present.

The current cache is therefore naturally aligned with morning-collected event
facts.

### Current one-off registration schedule

ADR 0089 currently runs:

- 12:47 normal;
- 13:47 recovery.

CONVEGA is refreshed by the registration wrapper only when today's successful
CONVEGA snapshot is absent.

### Initial multi-source recommendation

For the first multi-source/threaded implementation:

- **reuse the existing 05:10/05:30 event snapshots** for municipal/library/FACV
  registration projection;
- keep the existing translation-preparation pipeline;
- keep the proven 12:47/13:47 lifecycle schedule initially;
- keep CONVEGA's own refresh behavior;
- do not immediately add another full municipal source refresh or another AI
  translation cron.

This is the lowest-risk implementation because source collection, translation
and lifecycle delivery remain separate and bounded.

### Known freshness gap

A 05:10 municipal/library/FACV observation can miss registration information
published later that morning or afternoon.

Therefore "publish immediately when registration appears" must be interpreted
as:

**publish at the next successful lifecycle cycle after the bot has actually
observed current-open evidence.**

The current research does not yet prove whether one 05:10 source observation is
fresh enough for this product goal.

Before adding another sync, measure real source publication/update timing.

### Possible late-refresh follow-up

Only if production probes show meaningful same-day registrations commonly
appear after 05:10, consider one additional bounded registration-preparation
refresh before 12:47.

It should:

- refresh only lightweight candidate sources needed for registration;
- not rerun generic heavy poster/OCR work without a changed source identity;
- translate only newly discovered presentation facts needed for rich roots;
- remain one-shot and bounded;
- avoid adding a daemon, watcher or frequent poller.

Do not add this cadence speculatively.

## Source-by-source synchronization implications

### Municipal/Turismo

Best immediate reuse candidate.

Current 05:10 snapshot already includes future programme facts and Todo
participation enrichment across its bounded programme window.

Potential future late refresh should reuse the same source adapter/state rather
than create a parallel registration scraper.

### Biblioteca

Already refreshed inside 05:10 source preparation.

If reservation evidence is added to its existing detail extraction, reuse that
same snapshot first.

### FACV

Already refreshed in the 05:10 wrapper.

The technical gap is detail identity/registration enrichment, not another
calendar fetch schedule.

### CONVEGA

Retain current source-specific refresh until/unless it is intentionally moved
into a common registration-preparation command.

### Agenda Guardamar

This recommendation is superseded by ADR 0091. Agenda Guardamar is now a
candidate event-access source for paid tickets and free invitation claims.

Still do not infer current sale/claim state merely from generic ticket metadata:
the production probe must verify whether its occurrence-specific ticket URL is
itself reliable evidence of current availability and how not-yet-open /
sold-out states are represented.

### Ayuntamiento News

This may become an early-discovery source for municipal trips/campaigns that
appear before the monthly agenda.

If implemented, prefer integrating one bounded news/feed read into existing
municipal source preparation rather than creating a resident registration
watcher.

## Simultaneous registrations

### Decision: separate event roots

If several independent events become publishable on the same day, send
separate root cards.

Reasons:

- each event needs its own Telegram `message_id` for later replies;
- each event should retain its own poster;
- each card remains self-contained and tappable;
- lifecycle state stays one record -> one root;
- no ambiguity exists when deadline/full/closed arrives later.

### Do not use one combined text message

A combined message destroys the one-root-per-event contract and weakens poster
presentation.

### Do not use Telegram media albums as the default

Telegram can send media groups and returns individual Message objects, but an
album is a coupled visual unit and caption presentation differs from standalone
cards.

For this product it adds complexity without solving the core lifecycle need:

- independent roots become less visually independent;
- caption behavior is less suitable for full event cards;
- crash-safe multi-item album delivery is harder than sequential single-root
  sends;
- later replies still need per-item root IDs.

Therefore the default remains sequential standalone event cards.

### Bounded send volume

Do not invent an arbitrary permanent cap before observing real simultaneous
registration volume.

Implementation must nevertheless remain bounded.

The first production probe should count how many independent registration roots
would have been eligible on the same day across current sources.

If a safety cap is needed, remaining unsent records should stay eligible for
the recovery/next run; do not group them merely to satisfy a cap.

## Telegram capability review

The existing shared Telegram client already supports strict text replies using
`reply_parameters` with `allow_sending_without_reply=false`.

The existing photo sender returns a Telegram `message_id`, so a successful rich
photo root can be stored directly.

No Telegram framework is needed.

Photo captions remain limited to 1,024 characters, so rich roots require
curated compact presentation rather than raw source prose.

## Architecture review

### What can be reused safely

- source-specific normalized snapshots;
- global `Event` presentation fields as source projection targets;
- existing translation cache/preparation;
- existing `send_photo_url()`;
- existing strict `send_message(... reply_to_message_id=...)`;
- ADR 0089 semantic baseline and unknown/explicit-status logic;
- one-shot Termux scheduling;
- atomic small JSON state;
- crash-safe uncertain send principle.

### Required architectural changes before multi-source rollout

#### 1. Per-source freshness

Current one-off lifecycle globally gates on CONVEGA freshness.

Multi-source runtime must evaluate freshness per source.

A stale/unavailable CONVEGA source must not suppress a fresh municipal record,
and vice versa.

#### 2. Record-oriented planning

Current v1 may combine notices from multiple records into one publication.

ADR 0090 requires one event root per record.

Planner/delivery therefore becomes record-oriented.

#### 3. Root message state

State schema needs bounded `record_id -> root_message_id` metadata.

This is delivery/presentation state, not semantic source evidence.

#### 4. Crash-safe sequential sends

Multiple independent roots may be sent in one invocation, but not as one atomic
multi-send transaction.

Reserve, send and commit one record at a time so an ambiguous send blocks only
at a well-defined point and never creates an unresolvable partial batch.

#### 5. Ambiguous root recovery

Operator `resolve-sent` for an ambiguous root requires the verified Telegram
root message ID.

Do not mark a root sent without that ID.

#### 6. Rich presentation projection

`RegistrationRecord` should remain lifecycle-focused.

Source-owned rich presentation should be a separate payload keyed by the same
stable `record_id`, containing only presentation facts such as image/title/
place/time/description/audience.

Poster or translation changes must never look like lifecycle transitions.

#### 7. Translation readiness

Current cache is strong for titles and selected teasers but not guaranteed for
all rich-card fields.

Before implementation, inventory which exact presentation fields need new
bounded translation preparation.

Do not add per-message AI at delivery time by default.

#### 8. First-known deadline semantic

Add a separate notice kind for a deadline that first becomes known after
registration was already announced open.

Do not label it as a changed deadline.

### Overengineering explicitly rejected

Do not add:

- continuous source polling;
- webhooks;
- browser/Playwright;
- database/message broker;
- generic event bus;
- universal registration parser;
- generic media downloader;
- per-event worker;
- multi-level reminder ladder (7 days / 3 days / 1 day) for future opening;
- album-based lifecycle delivery;
- AI inside the 12:47 send path;
- a second independent Event model.

### Main current gaps

1. source-owned stable lifecycle identity for municipal one-off events;
2. FACV detail identity/action/deadline extraction;
3. first-party library reservation evidence;
4. optional Ayuntamiento News early discovery;
5. per-source freshness;
6. rich-card presentation completeness/translation;
7. root-message state and migration;
8. first-known-deadline semantic;
9. evidence about whether 05:10-only collection is fresh enough;
10. evidence about simultaneous root volume.

## Business-logic review

The target business flow is coherent:

1. source discovers a future event;
2. source-specific adapter establishes stable occurrence identity;
3. source may know no registration facts yet -> no lifecycle publication;
4. current-open appears with no boundaries -> rich root immediately;
5. future opening boundary appears -> store silently until day-before;
6. day-before future opening -> rich root;
7. current-open after an existing future-opening root -> concise reply when it
   adds actionable information;
8. later first deadline / deadline revision / full / closed / reopen ->
   compact strict reply;
9. event-day Morning/Tomorrow/Weekend rendering remains independent;
10. disappearance never means closure.

No step requires a generic scheduler or merged-event inference.

## Required next production reconnaissance

Before runtime implementation, perform one read-only probe that answers:

### Municipal snapshot

For every future event currently stored:

- source identity/provenance;
- event date/time;
- registration URL/contact/capacity/participation facts;
- image URL;
- title/teaser/details/place/audience completeness;
- translation-cache coverage;
- observed_at;
- earliest source date available when recoverable.

### FACV

Inspect raw Guardamar calendar rows/anchors to determine:

- stable tournament ID/detail URL;
- current registration action/contact/deadline;
- poster/image;
- publication/update metadata.

### Library

Find a current/future reservation activity and determine whether first-party
detail contains:

- reservation action/contact;
- capacity;
- unique event image;
- useful description;
- stable detail identity.

### Ayuntamiento News

Measure one bounded recent-news/feed request and inventory registration-shaped
campaigns:

- published/modified timestamps;
- stable post ID/URL;
- event date;
- registration start/end/action;
- unique image.

### Source timing

For all reviewed candidate posts/cards, capture publication/modified times.

The purpose is to determine whether the current morning-only collection misses
material same-day registration announcements and whether a second bounded
pre-12:47 refresh is justified.

### Simultaneous volume

Count how many independent root cards would have been eligible on each observed
day.

Do not choose a permanent per-run send cap before this measurement.

## Recommended implementation order after probes

1. municipal source projection, if identity/presentation evidence is sufficient;
2. state v2 + per-record root delivery + first-known deadline semantic;
3. per-source freshness abstraction;
4. FACV detail enrichment;
5. library enrichment;
6. Ayuntamiento News early discovery if it materially adds lead time;
7. only then consider a second daily source refresh if source timing evidence
   proves it valuable.

## Current recommendation

Keep the next implementation small:

- preserve 12:47/13:47 initially;
- reuse morning snapshots first;
- send one independent rich root per event;
- notify current-open immediately at next lifecycle run;
- use day-before as the default first notice for explicit future opening;
- reply for later lifecycle changes;
- add no album, daemon, queue, database or speculative second sync.

Then adjust source cadence only from measured production evidence.
