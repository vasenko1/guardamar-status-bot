# Long-lead event registration source reconnaissance

## Status

Source reconnaissance and repository-level technical reconnaissance completed
2026-10-03. No runtime code, cron or Telegram behavior is changed by this
research.

The purpose is to identify official/public-interest activities that are useful
to residents before the event day because registration, reservation, capacity,
authorization or an application deadline matters.

ADR 0089 remains the deployed architecture for one-off event registration.
This research determines which existing and future sources are suitable for
that lifecycle and which should stay in the separate course lifecycle.

## Executive conclusion

The project already has three different participation domains and they must not
be collapsed:

1. **Recurring/seasonal courses** already owned by
   `course_notifications.py`.
2. **One-off events requiring registration/reservation**, for which ADR 0089 is
   the right lifecycle.
3. **Ticket sales**, which are admission/ticket semantics and should not be
   relabelled as registration.

The largest immediate gap is not CONVEGA. It is the existing municipal
one-off-event pipeline: `municipal_agenda.py` already extracts registration
URL/contact and limited-capacity evidence for several real Guardamar activities,
but `event_registration_notifications.py` currently projects only CONVEGA
records.

Therefore existing Morning events do **not** automatically receive one-off
registration lifecycle notices. Reusing the lifecycle requires a
source-owned registration projection before cross-source Event merging.

## Existing lifecycle coverage

### CONVEGA one-off registration

Implemented and deployed under ADR 0089.

The source owns stable occurrence identity, current registration evidence,
same-day freshness and one-off lifecycle projection.

### Course/season registration

Already owned by `course_notifications.py`.

Current projections include:

- Sporttia municipal sports activities with registration intervals and
  registration-until-full;
- Dinamización Social with explicit registration start/end and until-full;
- Escuela de Música / Jardín Musical registration windows;
- chess-school and literary-group course facts where their current accepted
  snapshots provide them.

Do not duplicate these records into ADR 0089 one-off lifecycle.

### Ticket/admission sources

Agenda Guardamar and municipal agenda already retain occurrence-specific ticket
URLs/prices for eligible events.

Ticket purchase is not one-off registration. A future ticket-sale/sold-out
feature would require separate product semantics and evidence.

## Source reconnaissance

### 1. Municipal monthly agenda / Todo Cultura participation details

This is the highest-reuse one-off candidate.

The current municipal normalization model already contains:

- `registration_contact`;
- `registration_url`;
- `capacity_limited`;
- `participation_note`;
- occurrence date/time and source provenance.

The existing `_enrich_todo_participation()` layer attaches those facts only
to a matched occurrence.

Reviewed repository fixtures demonstrate real event patterns:

- youth drum workshop: registration at Centro Social Juvenil / WhatsApp;
- free guided route to the geodetic point: reservation email;
- drawing workshop: WhatsApp plus limited places;
- night hiking routes: registration contact, required equipment, limited
  capacity;
- Escape Room: three independent sessions with three independent Google Forms
  and limited places.

Recent public Todo Cultura pages show the same repeated pattern in September and
October 2026: guided routes, children's activities, Escape Room sessions and
other municipal activities may require prior registration or have limited
places.

Important authority rule: Todo Cultura is useful as a municipal-agenda
supplement/discovery surface, but a standalone proactive lifecycle should
prefer the primary municipal/Turismo/Agenda evidence already linked from the
event whenever possible.

### 2. Ayuntamiento News long-lead campaigns

Official source:
`https://www.guardamardelsegura.es/noticias/`

The official archive repeatedly publishes activities well before their start,
including participation/application documents.

Confirmed examples:

- Programa Dinamización Social 2026/27: online registration;
- Viaje Salón del Comic de Valencia, January 2026 publication for a later trip,
  with registration/authorization material;
- Programa Dale Vida a los Años 2026: published 17 December 2025, registration
  through 14 January 2026, limited places, later workshop starts;
- municipal contests/campaigns with explicit participation forms/deadlines.

The current municipal-agenda code already has a bounded Ayuntamiento News HTML
reader, but its candidate filter is intentionally restricted to fiesta
programme posts. Registration-shaped news posts are not currently discovered
by that component.

This is a strong source for early discovery before an event appears in the
monthly agenda.

### 3. FACV/FECV Guardamar chess tournaments

Existing source:
`https://www.facv.org/appwebfacv/public/staff/torneos/calendario_oficial.php`

The current `facv.py` adapter already stores future Guardamar tournament rows
for Morning/Tomorrow/Weekend, but only:

- title;
- start/end;
- place;
- organizer;
- calendar source URL.

Federation detail articles may contain materially earlier participation facts.
For the 2026 Open Dama Guardamar, the official federation article stated:

- registration closes when local capacity reaches 220 players;
- email and WhatsApp registration contacts;
- external organizer web form;
- competition date/venue and registration rules.

This is a strong one-off lifecycle candidate, but current FACV normalized state
does not retain a tournament detail URL/ID or registration facts.

### 4. Library activities

The official library adapter already has stable first-party detail URLs and
loads changed/new detail pages, but it currently extracts teaser/content facts,
not registration/reservation/capacity.

Municipal programme examples show children's library workshops with limited
places and reservation by phone/WhatsApp/library web page.

Before implementation, the same reservation text must be confirmed on the
first-party library detail surface. If present, library detail enrichment is a
good lightweight candidate because detail-page fetch/cache machinery already
exists.

### 5. Dale Vida a los Años

Official municipal publication:
`https://www.guardamardelsegura.es/2025/12/17/programa-dale-vida-a-los-anos-2026/`

This is long-lead registration but structurally a recurring/seasonal course
programme, not a one-off event:

- registration deadline;
- limited places;
- resident priority;
- admission list;
- multiple workshops and group schedules over months.

If automated, it should be added as another course-source projection under
`course_notifications.py`, not ADR 0089.

### 6. Sporttia municipal sports

Already implemented under the course lifecycle.

The official Sporttia catalogue contains season dates, new-registration windows
and registration-until-full semantics. No ADR 0089 duplication is needed.

### 7. Municipal youth trips and excursions

Recurring historical pattern, e.g. comic/manga trips:

- municipal announcement before travel date;
- registration mandatory;
- limited places;
- minor authorization where applicable;
- municipal registration form/office/contact.

These are true one-off events and should eventually use ADR 0089 semantics.
Ayuntamiento News is likely a better early-discovery surface than waiting for
the monthly agenda.

### 8. School/institutional bookings

Municipal educational dossiers can expose registration months before delivery
of school activities.

These are institution/school booking workflows rather than general resident
events. Exclude from the public one-off lifecycle unless product scope changes.

### 9. Municipal contests / parade participation

Carnival, desfile and similar municipal calls may expose participant
registration deadlines.

They may fit a broader participant-opportunity lifecycle, but are lower
priority than event attendance/visitor registration and should not be included
automatically without an explicit product decision.

## Clarification: registration information may open immediately without dates

The source reconnaissance was rechecked against the deployed ADR 0089 engine.

A registration start date and end date are **not required** before proactive
publication. The decisive distinction is current source-backed availability:

- if the accepted source now provides an actionable registration instruction
  tied to the occurrence (form/CTA, registration contact/place, or an explicit
  current-open instruction), project `status="open"`;
- keep `registration_start_date=None` and/or
  `registration_end_date=None` when the source does not publish those facts;
- the first observed `open` state is publishable immediately as
  "Идёт запись";
- never substitute `observed_at` for a missing registration start date;
- no opening/closing boundary reminder is created for a boundary that was not
  explicitly published;
- a bare statement that registration will be required later, or that details
  are forthcoming, is not current-open evidence;
- an explicit future registration window prevents a current-open claim before
  its stated start.

This behavior already matches the deployed planner contract:
`RegistrationRecord.registration_start_date` and
`registration_end_date` are optional, while first-seen `open` is an active
publication.

One follow-up is required before multi-source rollout. Today, if an already
announced undated open registration later acquires its first explicit end date,
the planner classifies it as `deadline-changed`. For municipal/FACV/library
sources this should instead distinguish "deadline first became known" from
"previously known deadline changed".

The municipal investigation also confirms that Todo Cultura participation
enrichment is applied across the dates in the accepted programme window, not
only on the event day. The collector prioritizes a rolling 7-day window while
also considering unchecked local candidates within a 44-day horizon. Therefore
future one-off registration facts can already enter
`state/municipal_agenda.json` before the event day; the remaining problems are
stable source identity, evidence ownership and lifecycle projection.

## Why Morning Event objects cannot be fed directly into ADR 0089

The global `Event` model already has `registration_url`,
`registration_contact` and `capacity_limited`, but those fields are display
facts, not sufficient lifecycle evidence.

A proactive lifecycle additionally needs:

- stable source-owned identity;
- source URL/authority;
- same-day observation freshness;
- explicit current-open evidence **or** an exact future registration boundary;
- occurrence-bound action/contact/open-state evidence; boundary dates remain optional;
- last-explicit-status preservation across unknown source states.

The merged Morning event list must therefore **not** be scanned after
`_merge_events()`. Cross-source merging is intentionally additive and can
retain facts from different observations; it also loses the precise source
identity required for lifecycle transitions.

Each accepted source should project its own normalized source record to
`RegistrationRecord` before global Event merging.

## Technical gap matrix

### Municipal agenda

Already has most participation facts, but lacks an ADR-0089-ready source-owned
registration identity/status layer.

Current event key `(title, start_date, start_time)` is useful for local
deduplication but is not durable enough as lifecycle identity when a source
corrects the date/time.

Needed before implementation:

- determine which source inputs expose durable article/session IDs;
- retain explicit registration evidence/status separately from additive Event
  fields;
- preserve source URL per one-off registration record;
- use same-day municipal snapshot freshness;
- define deterministic dedup when the same event later appears through another
  municipal surface.

### Ayuntamiento News

Existing bounded HTML transport can be reused.

Needed:

- a separate registration-campaign candidate filter, not an expansion of the
  current fiesta-only programme filter;
- bounded search window and candidate limit;
- article identity from dated post URL or a stable WordPress ID if public REST
  is validated;
- deterministic extraction of event date and current registration evidence;
  registration boundaries/capacity are retained when explicitly published but
  are not required for an immediate `open` projection;
- dedup with monthly municipal agenda.

No new daemon or browser is justified.

### FACV chess

Needed:

- production probe of raw calendar row links/IDs;
- determine whether stable tournament ID/detail URL is exposed;
- bounded detail fetch only for future Guardamar rows;
- source-specific registration action policy for federation/organizer links;
- parse current open/full/deadline only from explicit evidence.

Do not infer open merely because a tournament exists in the calendar.

### Library

Needed:

- production probe of current/future detail pages with reservation activities;
- verify first-party detail contains reservation/contact/capacity text;
- if yes, extend the existing changed-detail extraction rather than create a new
  source client;
- use detail URL as a likely stable source identity only after verifying its
  behavior across date corrections.

## Recommended implementation order after probes

1. Municipal one-off participation projection from existing municipal state.
   This has the highest reuse and already contains real registration facts.
2. Ayuntamiento News early registration-campaign discovery for trips and other
   activities that appear before the monthly agenda.
3. FACV/FECV tournament detail enrichment.
4. Library reservation enrichment if first-party detail evidence is confirmed.
5. Dale Vida as a separate course-notification source, not one-off lifecycle.

Ticket-sale lifecycle and municipal contest participation remain separate
future product decisions.

## Required production probes before code

### Municipal state probe

Inspect the current `state/municipal_agenda.json` without modifying it:

- fetched_at;
- future events carrying registration URL/contact/capacity;
- source provenance;
- session source keys;
- number of days between observation and event date.

This determines how much ADR 0089 can reuse immediately without new network
requests.

### Ayuntamiento News probe

From Termux, bounded/read-only:

- fetch `/noticias/`;
- inspect recent dated article links containing registration-shaped language;
- test whether main-site WordPress REST is anonymously available;
- measure response size/time;
- inspect exact HTML/links for representative trip/workshop posts.

### FACV probe

From Termux, bounded/read-only:

- inspect raw Guardamar calendar rows including anchors/attributes currently
  discarded by `facv.py`;
- identify stable tournament IDs/detail URLs;
- fetch one reviewed Guardamar tournament detail and inventory registration
  contacts/actions/deadlines/capacity.

### Library probe

From current official library agenda/detail pages:

- locate a limited-capacity/reservation activity;
- inspect whether reservation data exists in first-party detail markup;
- measure whether current detail cache already fetches all required bytes.

## No-code decision at this stage

Do not add a generic "scan every Morning Event for registration" layer.

The reusable part of ADR 0089 is the lifecycle/delivery engine. The source
projection must remain source-specific and evidence-owned.

This preserves the project's main rule:

**prefer a missed proactive notice over a false registration-state claim.**


## Product requirement: rich first-open registration card

The first proactive registration publication should ideally be a complete
event card, not a bare lifecycle line.

When an occurrence first becomes publishably `open`, prefer one Telegram
photo message containing:

- the event-specific official poster/image, when a unique reviewed image exists;
- the Russian event title;
- event date and time;
- place / meeting point;
- a concise translated description of what the event is;
- audience/age/duration/route or other material participation facts when known;
- registration action/contact;
- explicit deadline/start boundary when published;
- capacity/until-full conditions when published;
- material participation requirements/cost when applicable.

The image is presentation enrichment, not registration-state evidence. Missing
or temporarily inaccessible media must not suppress an otherwise valid
registration publication.

Only an image uniquely attributable to the occurrence should be used. A generic
monthly programme poster or ambiguous image should not be attached merely
because it comes from an official source.

### Reuse of existing runtime capabilities

The project already has the needed media primitives:

- global `Event` has `image_url`;
- municipal `SourceEvent` has `image_url`;
- Tomorrow already validates selected official HTTPS poster URLs before use;
- Telegram transport already supports remote photo messages through
  `send_photo_url()`.

The future one-off registration extension should reuse that media path and add
source-specific image policies rather than create a second downloader/browser
pipeline.

### Presentation projection, not merged Event scanning

Do not construct the rich registration card by scanning the already merged
Morning `Event[]`.

Keep lifecycle evidence and presentation enrichment separate:

- source-owned registration projection supplies stable identity/status/action;
- the same accepted source record supplies or deterministically links the
  event presentation facts;
- optional poster/description fields do not affect lifecycle transitions.

A small source-owned presentation payload should therefore accompany a
`RegistrationRecord` (or be keyed by the same `record_id`) without becoming
part of the semantic status baseline.

This is especially important for `image_url`: poster changes must never look
like registration-state changes.

### Translation requirement

A first-open registration publication should use the existing event translation
cache rather than perform a second independent translation of the same title
or teaser.

The current cache reliably covers titles and selected municipal teasers. Rich
cards require a follow-up inventory of which additional presentation facts are
already Russian/deterministic and which remain Spanish (for example selected
`details`, participation requirements, audience labels or schedule notes).

Prefer extending the existing bounded translation-preparation phase before the
12:47 registration publication. Do not introduce per-message noon AI work when
the source was already collected during the morning event refresh.

If a newly discovered source appears too late for cached translation, the
implementation needs an explicit product fallback policy. Do not silently mix
Spanish long-form prose into an otherwise Russian registration card.

### Telegram caption constraint

Telegram photo captions are currently limited to 1,024 characters after
entity parsing. Therefore "maximally detailed" means "all material resident
facts in a curated card", not a verbatim copy of the source page.

Default behavior should be:

1. one photo + complete compact caption when all material facts fit;
2. prioritize date/time/place, event description, registration method,
   deadline/capacity and participation requirements;
3. omit low-value prose before omitting registration conditions;
4. if critical material cannot safely fit, use an explicitly designed fallback
   instead of truncating facts.

A two-message photo-plus-long-text fallback is acceptable only when the event
genuinely needs more than the caption can hold; one self-contained photo card
remains the preferred resident experience.

### Lifecycle media policy

Use the rich photo card primarily for the first current-open announcement (and
optionally a true reopening if the card is still current).

Routine deadline/full/closed updates should normally stay compact text-only
unless a later product decision justifies repeating media. This avoids visual
spam while making the initial discovery post prominent and useful.

### Additional production probes

For each candidate source, the next read-only probe should inventory not only
registration evidence but also presentation completeness:

- official event-specific image/poster URL;
- image host/path/content type and whether Telegram can fetch it directly;
- title/teaser/details already retained in source state;
- place/time/audience/duration/route completeness;
- which presentation fields are already covered by translation cache;
- whether the source page exposes a unique event image or only a generic
  programme/month poster.

This media/presentation inventory is required before choosing the first
multi-source implementation target.
