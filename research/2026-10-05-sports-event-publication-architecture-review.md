# Sports event publication and event-access architecture review — 2026-10-05

## Status

Completed architecture/source review. No production code, cron, state or Telegram
publication is changed by this research branch.

This review supersedes only the **publication-surface** conclusion in
`research/2026-09-17-guardamar-sports-event-sources.md` that sports needed no
separate resident-facing treatment. Its collection principles remain valid:
source-specific bounded adapters, one normalized Event stream, official sources,
no browser, no per-sport daemon/database/generic scraper.

## Product requirements confirmed

The operator clarified that the desired resident lifecycle is:

1. discover an event and, when advance access exists, publish one detailed
   event-access root;
2. keep registration/reservation/ticket changes as replies to that root,
   including tomorrow/today opening or closing boundaries, full/closed/reopened;
3. include the sporting event in normal planning before the day;
4. publish a separate current-day sports reminder even when the event was
   already announced the previous evening/weekend;
5. keep sports out of the 07:30 Morning Digest once the current-day sports
   surface is live;
6. write sport copy for a Russian-speaking resident, not as raw federation/team
   database rows.

The planned and current-day mentions are intentional repetition serving
different decisions. They must not be deduplicated against one another.

## Clean architecture result

There must be **one event fact pipeline** and several presentation/delivery
projections, not several sports systems:

```text
official source adapters
        |
        v
normalized Event + source-owned access facts
        |
        +--> event-access root + threaded lifecycle replies
        |
        +--> next-day / weekend planning (sports subsection)
        |
        +--> current-day sports reminder
        |
        +--> Morning Digest (non-sport events only)
```

Do not add:

- a sports database;
- a generic sports provider registry;
- a generic sports crawler;
- a resident sports daemon;
- a per-sport scheduler/state file;
- a sports-specific registration state machine;
- browser automation;
- runtime LLM composition.

## Reuse existing planning surfaces for "tomorrow"

A new daily evening `sports tomorrow` post is unnecessary.

Existing planning already has the right cadence:

- Friday `Афиша выходных` at 19:15 + 20:15 recovery covers Saturday and
  Sunday;
- `Завтра в Гуардамаре` at 19:25 + 20:25 recovery covers
  Sunday-Thursday evenings;
- Friday/Saturday next-day runs are intentionally suppressed because the Friday
  weekend digest already covers those target days.

Decision direction:

- add a clearly separated `🏅 Спортивные мероприятия` subsection inside
  `Завтра в Гуардамаре`;
- add the same sports subsection inside each Saturday/Sunday block of
  `Афиша выходных`;
- do **not** add another evening sports cron.

This is both quieter for residents and lighter for Termux.

## Add one new current-day sports publication

Create one standalone current-day surface, e.g.

`🏅 Спортивные мероприятия сегодня — 17 октября`.

It reads accepted local event snapshots only, sends nothing when no qualifying
sport is present, and has its own tiny at-most-once delivery state.

A practical first schedule is:

- 08:25 Europe/Madrid primary;
- 09:25 recovery.

Reasons:

- after the 07:30 Morning Digest and 08:05 SUMA;
- before most daytime sport while the previous-day planning remains the
  earliest discovery surface;
- no source network or AI work is required in this command;
- recovery remains before late-morning workflows.

The exact minutes should still be verified on production crontab before
deployment, but no new scheduler/daemon is justified.

## Sports leave the Morning Digest

Once the current-day sports path and cron are deployed and verified, events
with explicit `Event.sport != None` should not be rendered in Morning Digest.

Do not remove them before the new path is operational. Deployment must make the
new current-day path and the Morning filter effective together, with a
pre-deploy cron check and a post-deploy preview/status check.

## Minimal normalized-model change: Event.sport

Current FACV/Pesca snapshots already know:

- FACV: `sport="chess"`;
- Pesca CV: `sport="fishing"`.

That fact is lost when both become `Event(category="event")`.

Add one optional canonical presentation/relevance field:

```python
sport: Optional[str] = None
```

Do not overload `category`. It already carries event/exhibition-style
presentation semantics.

Use a small canonical vocabulary owned by adapters, for example football,
futsal, volleyball, basketball, running, cycling, triathlon, tennis, chess,
fishing, petanque, sailing, kayak, swimming. The renderer maps those codes to
Russian labels/icons deterministically.

### Merge contract

`_merge_events()` must preserve sport identity:

- known + None -> known;
- same known + same known -> same known;
- different known sports -> never fuzzy-merge as one event.

This prevents one broad title/place overlap from accidentally merging two
different competitions.

## Sports classification must remain source-backed

Do not introduce a global keyword classifier over Russian/Spanish event titles.

Preferred evidence order:

1. explicit sport/discipline field from a federation;
2. official source category/provenance such as a reviewed Turismo sports
   category;
3. a narrow source-specific deterministic mapping when a mixed official
   programme explicitly names an unambiguous sport.

Do not classify CONVEGA hiking as sport merely because it is physical activity:
the operator introduced the sports work **in addition to** the already accepted
guided-hike/event-access product.

## Human-readable Russian sports copy

Raw federation rows are not acceptable publication copy.

Every item should answer as many source-backed questions as are useful:

- what sport is this;
- what kind of match/competition/race;
- who competes or who may participate;
- start/end/schedule;
- venue;
- league/level/category when useful;
- distance/format;
- official time limit or duration when available;
- admission or registration action when current and explicit.

Examples of presentation intent:

```text
⚽ Футбол — Guardamar против Sporting Saladar
Матч взрослой команды, Segona FFCV · группа 8.
🕐 18:30
📍 ...
```

```text
🏐 Волейбол — Guardamar против CV Callosa
Матч женской взрослой команды, 3-я дивизия · группа 3.
🕐 19:00
📍 ...
```

Do not expose opaque sponsor strings such as `GRUPO NEXUS GUARDAMAR` as the
whole explanation. Source-specific adapters may use an exact reviewed local
team alias (for example display the known local side as `Guardamar`) while
retaining source identity internally.

Proper opponent/club names do not need invented Russian translations.

### Duration policy

The existing Event model already has `duration_minutes`, `details`,
`schedule_note`, `audience_label`, `teaser`, place and access fields.
Do not add another general duration model.

- use official start/end/duration when provided;
- use an official race time limit as a labelled **time limit**, not as claimed
  event duration;
- derive an approximate duration only from a separately reviewed deterministic
  sport/competition rule, clearly marked approximate;
- otherwise omit duration rather than guess.

The official Turismo page for Media Maratón Guardamar 2026 demonstrates the
desired rich shape: 09:30 start, 21.097 km and 10.5 km distances, 2 h 30 min
and 90 min time limits, start/finish location, 800 participants, bib-pickup
windows and route/service facts.

Reference:
`https://guardamarturismo.com/media-maraton-de-guardamar-2026/`

## Reuse the existing event renderer rather than build a second formatter

The current shared event renderer already understands:

- times/end times;
- details;
- duration;
- audience;
- teaser;
- place/meeting point;
- registration/ticket/access lines;
- programme/session grouping;
- Telegram length bounds.

Preferred implementation shape:

- a small pure sports-presentation helper maps `Event.sport` to Russian
  label/icon and produces presentation-only decorated Event titles;
- Tomorrow/Weekend/Sports Today continue to use the existing
  `build_event_section()` / event-detail contract.

Do not duplicate all event rendering in a sports-only renderer.

Source adapters still own team-name normalization and source-specific useful
details.

## Multi-day sport

Current next-day logic intentionally suppresses middle days of generic
date-range events because a range does not always prove daily activity.

For federation competitions, however, an adapter may explicitly prove that the
competition is active on each day. The source reader already returns that event
for the target day.

Sports planning should therefore allow an active `sport != None` event on a
middle day when the source adapter's day reader has explicitly returned it,
while retaining the first/final-day rule for generic non-sport ranges.

Sports Today naturally shows each source-proven active competition day.

## Event-access v2 is the correct advance-access mechanism

ADRs 0090-0092 already provide the reusable semantics needed for sport:

- one event root;
- `registration`, `reservation`, `ticket`;
- multiple source-proven options/sessions;
- opening tomorrow/today;
- closing tomorrow/today;
- first-known/changed deadline;
- open/full/closed/reopened;
- changed action;
- added option;
- strict replies to the stored root;
- one crash-safe uncertain outbound reservation.

Do not create any sports-specific registration lifecycle or state machine.

New sources should expose explicit source-specific access projections and feed
this existing engine.

The current runtime runner is still CONVEGA-only. Multi-source rollout should
add explicit source loaders/freshness checks, not a generic plugin registry.

## Important event-access timing gap

The current event-access cron runs at 12:47 and 13:47.

That is too late for some legitimate same-day closing reminders. The reviewed
Pesca CV provincial Guardamar competition on 17 October 2026 has an official
convocatoria whose registration deadline is 13 October at 12:00. A 12:47
checkpoint can send the previous day's `closing-tomorrow`, but cannot send a
useful `closing-today` before that deadline.

The state machine itself is correct: `_closing_notice()` refuses to emit a
today reminder after an explicit closing time.

Preferred correction before enabling sports access:

- move the existing two event-access one-shots earlier rather than add a third
  sports registration scheduler;
- a candidate window is 09:47 primary + 10:47 recovery.

This keeps the same two invocations. For CONVEGA, the 09:47 run refreshes when
the <=90-minute contract requires it; the 10:47 recovery can reuse that accepted
snapshot within 60 minutes, so the normal request count does not increase.

A source with an unusually early closing time may still rely on
`closing-tomorrow` unless its real contract later justifies an even earlier
checkpoint. Do not invent per-event timers.

The final minute choice requires a production crontab collision check before
deployment.

## Photo event roots: approved architecture, missing runtime implementation

The operator's desired main card is already the ADR 0090 target:

- one event-specific official image when uniquely attributable;
- complete compact Russian event card;
- later access changes as strict text replies;
- do not repeat the poster for routine updates.

But current runtime is **text-root only**:
`event_registration_notifications.py` imports/uses `send_message()` for
both roots and replies.

The repository already has the required media primitives:

- `Event.image_url`;
- `telegram.send_photo_url()`;
- Tomorrow Events' validated remote-photo delivery with deterministic
  photo->text fallback;
- crash-safe uncertain publication state.

### Minimal photo-root extension

Add an optional **presentation-only** `image_url` to `EventAccessRecord`.

Do not put it in semantic event-access state. Current
`candidate_record_state()` already persists only source/access-kind,
event dates, options, audience/root IDs and triggers; title/details are also
presentation-only.

Therefore a first photo-root implementation needs no event-access state-version
bump and no database/media cache.

Delivery rule:

1. source-specific projection validates/allowlists one unique official image;
2. reserve the existing uncertain root operation;
3. if the complete root card fits Telegram's 1024-character photo-caption
   limit, call `send_photo_url()`;
4. on confirmed success, store the returned root message ID exactly as for text;
   returned photo file ID need not be stored because roots are not edited;
5. on a deterministic remote-media rejection, clear/re-reserve and send the
   same complete card as text;
6. on timeout/network/5xx/ambiguous photo response, keep uncertain and never
   auto-send a text duplicate;
7. when the complete critical card does not fit 1024, prefer one text root over
   a photo + overflow transaction.

This reuses the proven Tomorrow media pattern while preserving ADR 0090 crash
safety.

Use only an event-specific official poster/image. A generic monthly programme
poster, venue photo or team logo is not a substitute merely to force media.

## Generic access wording has an implementation gap

ADR 0091 already specifies root wording for registration/reservation/ticket.

The current runtime `_root_heading()`, `_opening_text()` and
`_reply_block()` still use registration-specific phrases for many notices
even when `access_kind` is `reservation` or `ticket`.

Fix this generic wording before the first sport reservation/ticket source is
enabled. This is a core event-access completion, not sports-specific logic.

## Heterogeneous access kinds remain explicitly deferred

ADR 0091 intentionally places one `access_kind` on one event root.
If a real sport source later proves one event simultaneously needs participant
registration **and** spectator ticket sale under the same event, review that
source explicitly. Do not redesign the model speculatively now.

Most reviewed target shapes remain single-kind:

- mass race -> participant registration;
- league match -> ordinary event or spectator ticket;
- federation competition -> participant/club registration;
- free spectator entry -> ordinary Event access presentation, unless a free
  ticket/invitation must be claimed.

## Planning posts should not become replies to access roots

The detailed event-access root is one-event identity.

Tomorrow/weekend/current-day sports posts are editorial aggregates and may
contain several events. Making an aggregate a reply to one event root would
create false ownership; making one reply per event would recreate the message
noise this design is avoiding.

Therefore:

- access lifecycle changes reply to the event root;
- planning/current-day aggregate posts remain standalone;
- no second semantic event identity is created.

A future root deep-link may be considered only if it can be added cheaply and
unambiguously; it is not required for the first implementation.

## Source/freshness review

### FACV + Pesca CV

Already implemented and production-probed.

They refresh in the existing 05:10 event wrapper. No new cron is needed.

Pesca CV HTML is already about 1 MiB, so do not re-fetch it for Sports Today or
each planning message.

Existing source codes should project:

- FACV -> `sport="chess"`;
- Pesca CV -> `sport="fishing"`.

### Pesca CV access

The official 2026 convocatorias page lists:

- 17 October 2026;
- Provincial Alicante;
- Mar-Costa Captura y suelta;
- Playas La Roqueta y Centro — Guardamar.

References:

- `https://federacionpescacv.com/convocatorias-clasificaciones-2026/`
- `https://federacionpescacv.com/competiciones-de-nuestros-clubes/`

Prior live/source reconnaissance already proved that its official convocatoria
contains club-mediated registration, an exact deadline and event schedule.
That access must be projected from the convocatoria, not inferred from the
calendar row.

Do not tell ordinary residents to self-register when the official process is
club-mediated.

### FEPyC vs regional Pesca dates

The regional competition table contains FEPyC Mar Costa Dúos rows beginning
23 November, while the national FEPyC event page identifies the actual XVI
Campeonato de España date as **26-29 November 2026** in Guardamar.

Reference:
`https://www.fepyc.es/26MC26`

Do not create a generic source-precedence engine.

Use fact-level authority:

- national championship competition dates -> national FEPyC;
- regional/local convocatoria and local organization/access facts -> FPCV when
  explicitly published.

### FVBCV volleyball

The official `https://fvbcv.com/competiciones/` page is server-rendered HTML
and currently exposes 2026/27 competition navigation plus jornada tables with
date, time, competition group and home/away teams.

The current live page demonstrates why humanization is mandatory:
`GRUPO NEXUS GUARDAMAR` is opaque without the label `Волейбол`.

A future adapter should use exact reviewed local team identity and publish
Guardamar-hosted matches. It should not publish scores/results as part of this
feature.

Before implementation, production-probe:

- response size/time/redirect/MIME;
- exact team IDs/names;
- whether venue is recoverable;
- how postponed/cancelled/withdrawn fixtures are represented.

### FFCV football

Do not use a static season PDF as the final live fixture truth.

A future adapter is gated on a production probe of an official live FFCV
HTML/JSON path that can supply current fixture date/time/venue and, ideally,
postponed/suspended/cancelled status.

Results/standings/live scores remain out of scope.

### Turismo / mass participation sport

The official Media Maratón page proves that Turismo can carry high-value
resident presentation facts: event image/article, start, distances, time
limits, capacity, route, bib pickup and services.

A future Turismo sports discovery adapter should use source-backed sports
category/provenance or another reviewed deterministic source contract. Do not
globally classify arbitrary municipal titles by keywords.

When Turismo explicitly delegates registration to an external timing/provider
page, that provider may own only the delegated access facts (registration,
price/deadline/availability), not independent event discovery.

## Current-day delivery state

Sports Today requires one small publication state, not sports event storage:

```text
version
target_date
status = uncertain | sent
message_id (sent only)
```

Its semantics are exactly the existing Tomorrow at-most-once state semantics.

A small shared dated-publication state primitive is justified because the state
shape and crash-safety behavior are identical. Prefer extracting/renaming that
exact primitive with compatibility aliases/tests rather than copying a second
~130-line state implementation or building a generalized workflow framework.

This is the appropriate level of reuse; do not generalize source collection or
all Telegram workflows.

## Current-day Sports rendering

Use the same underlying Event details as planning but allow richer copy because
the resident is deciding what to attend **today**.

A typical item may be several short lines; do not optimize for the fewest
characters.

For multiple events, keep one message and complete event blocks. Avoid
multi-message transactions in v1. Source adapters should keep descriptions
curated enough that the normal <=4096 Telegram bound can accommodate the
expected daily volume. If real production volume later breaks that assumption,
measure it before designing pagination.

Sports Today is normally text. The durable image belongs primarily to the
event-access root; Tomorrow already supports one image when its whole planning
publication contains exactly one eligible editorial unit.

Do not repeat a poster on every current-day/registration update merely because
media exists.

## Cancellation/postponement

Do not build a generic cancellation lifecycle before a real source contract
requires it.

However a league source must not be enabled from a schedule source known to be
stale when official live status exists elsewhere.

Source acceptance should verify how the federation represents postponed,
suspended, cancelled or withdrawn fixtures.

The same-day fresh sports view is a useful correction surface, but explicit
cancellation notifications beyond that are a separate reviewed product decision.

## Scope of regular team sport

Collection may be broader than publication.

Start new league adapters with the clearest useful slice (adult/senior
Guardamar-hosted matches) and measure real volume. Expand youth categories
after observing cardinality; do not build a hard-coded assumption that only
senior sport can ever be useful.

Every published fixture must physically take place in Guardamar; an away match
of a Guardamar team is not a Guardamar city event.

## Proposed implementation sequence

### Slice 1 — publication foundation, no new network source

1. add `Event.sport`;
2. propagate FACV/Pesca sport codes;
3. make `_merge_events()` preserve/guard sport identity;
4. add the pure Russian sport label/decorating helper;
5. split sports into a dedicated subsection in Tomorrow and Weekend;
6. add local-only Sports Today + at-most-once state + preview;
7. add 08:25/09:25 rows to the existing event-planning cron installer;
8. remove sport events from Morning only in the same deploy where Sports Today
   is installed/verified;
9. update tests/docs.

This gives a complete resident product immediately using already deployed
chess/fishing sources and exercises no new source load.

### Slice 2 — complete the generic event-access presentation

1. access-kind-correct registration/reservation/ticket wording;
2. optional presentation-only image URL;
3. crash-safe photo-root using existing Telegram/Tomorrow semantics;
4. move the two event-access checkpoints earlier after production cron review;
5. preserve text-root fallback and existing v2 semantic state.

This is generic infrastructure already promised by ADR 0090/0091, not a sport
framework.

### Slice 3 — Pesca access + national-date correction

- exact convocatoria/access projection;
- club-mediated audience wording;
- FEPyC fact-level national date authority;
- targeted tests.

### Slice 4 — FVBCV

After production source probe, add adult/senior home matches first and measure
volume.

### Slice 5 — FFCV

Only after a current official live fixture contract is proven.

### Slice 6 — Turismo mass sport / delegated registration

After a source-category/discovery production probe, add races and other
resident participation events; use delegated registration providers only for
their explicit access facts.

Then evaluate basketball, tennis, cycling/triathlon, sailing/kayak and other
official sources one by one. No broad upfront provider framework is justified.

## Required tests before rollout

At minimum:

### Event/sport identity

- optional sport does not affect non-sport behavior;
- FACV/Pesca sport survives projection and merge;
- None + sport merges to sport;
- different known sports never fuzzy-merge;
- Morning excludes sport while Tomorrow/Weekend/Sports Today retain it.

### Planning/current-day

- Tomorrow has separate sports subsection;
- Friday Weekend carries Saturday/Sunday sports;
- Friday/Saturday next-day suppression remains unchanged;
- Sports Today intentionally publishes even when yesterday's planning state was
  sent;
- no sport -> no Sports Today message;
- primary success makes recovery no-op;
- uncertain blocks automatic duplicate;
- multi-day source-proven sport can appear on the relevant current day;
- Telegram message bounds keep complete blocks.

### Event-access

- all existing v2 planner/state tests remain green;
- registration/reservation/ticket wording;
- closing-today before explicit time and no closing-today after it;
- photo root success stores the root ID;
- deterministic photo rejection -> text fallback only after safe clear/re-reserve;
- ambiguous photo failure -> uncertain and no text duplicate;
- >1024 critical root -> text root;
- image changes never create semantic lifecycle changes.

### Source-specific future adapters

- exact locality;
- fresh-date requirements;
- cancellation/postponement representation;
- team display normalization;
- no scores/results publication;
- last-good fail-closed behavior.

Run the targeted suites plus the complete repository suite and a production
Python compile/import smoke check before deploy.

## Rollout safety

Do not let sport disappear from existing publications between code and cron
changes.

Before deployment:

1. verify canonical `origin/main` and reviewed target SHA;
2. inspect live production crontab;
3. verify the intended Sports Today and moved event-access slots have no
   operational collision;
4. deploy code;
5. run Sports Today and Tomorrow previews with no Telegram/state writes;
6. install/update the existing managed event-planning cron block;
7. verify the installed rows exactly;
8. verify event-access v2 status remains valid;
9. only then allow the next normal scheduled publications.

No historical event should be replayed merely because `sport` is added.

## Final architecture judgment

The clarified product does **not** justify a new sports subsystem.

The smallest coherent design is:

- one normalized Event stream with one added explicit `sport` fact;
- existing Tomorrow/Weekend as the "before the day" surface;
- one new local-only current-day sports publication;
- existing event-access v2 as the entire advance registration/reservation/ticket
  lifecycle;
- completion of ADR 0090 photo roots using already proven Telegram primitives;
- source-specific adapters/freshness rules added only when a real Guardamar
  source contract is proven.

This maximizes reuse while keeping each responsibility explicit and recoverable.


## Review cycle 2 — newly found gaps and corrections

This cycle intentionally tried to invalidate the prior conclusion rather than
confirm it.

### Competition context is required resident information

A match row is incomplete if it only says the sport and opponents.

For a league/cup/tournament source, publish the source-backed competitive
context when available:

- competition name / division;
- group;
- round / jornada;
- qualifying stage;
- quarter-final / semi-final / final;
- playoff;
- friendly / exhibition match when explicitly identified as such;
- age/sex/team category when it materially explains who is playing.

Do not infer knockout importance from calendar position or words such as
`torneo`.

The current 2026/27 FFCV official Segona FFCV Group 8 calendar proves that this
metadata can be explicit: the document identifies `Segona FFCV, Grup 8` and
individual `Jornada` numbers. For example, Guardamar Soccer vs Sporting
Saladar is in Jornada 5 on 25 October 2026.

This does **not** yet justify a new generic competition object. The preferred
first representation is one or more ordered, source-backed `Event.details`
lines such as:

`Segona FFCV · группа 8 · 5-й тур`

or:

`Кубок ... · полуфинал`

A dedicated model field should be introduced only if real adapters prove that
`details` cannot preserve ordering/authority without ambiguity.

### Multiple race distances cannot be stored as bare distance details

The shared renderer's `_normalized_event_details()` treats multiple
distance-only strings as route alternatives and collapses them to one maximum
distance marked approximate.

Therefore this would be wrong for a two-race event:

```python
details=("21,097 км", "10,5 км")
```

because the renderer may turn it into one approximate maximum.

Use labelled facts instead, for example:

- `Полумарафон: 21,097 км · лимит времени 2 ч 30 мин`;
- `10K: 10,5 км · лимит времени 1 ч 30 мин`.

Those facts remain distinct and accurately describe separate disciplines.

The official Turismo Media Maratón 2026 page explicitly provides both
distances and their separate maximum times, so the distinction is source-backed.

### ADR 0090 promises material date corrections, but runtime does not emit them

ADR 0090 explicitly lists `material event-date corrections` among notices
that should reply to an existing root.

Current `candidate_record_state()` silently replaces
`event_start_date/event_end_date`, while `plan_event_access_record()`
creates notices only from option opening/status/deadline/action/closing changes.

Therefore a changed event date currently updates stored state with **no reply**.

This is a real generic event-access implementation gap, not a sports-only
feature request.

Because event dates already exist in v2 state, a date-change reply can be added
without inventing a second lifecycle or a new storage subsystem.

Time/place/cancellation changes remain a broader question and are reviewed
separately below; do not pretend the date-correction promise is already
implemented.

### A canonical root creates a responsibility for material event changes

Once the root is intentionally a detailed event card, registration state is not
the only fact that can make it stale.

For events with an existing access root, the architecture must distinguish:

1. access-only changes -> existing event-access notices;
2. material event-date changes -> reply to root (already promised by ADR 0090);
3. explicit cancellation/postponement from a responsible source -> should be
   reviewable as a root reply for rooted events rather than leaving the card
   misleading;
4. ordinary league fixtures without an access root -> current planning/current-
   day source freshness is enough; do not create a root merely to monitor them.

Do **not** turn event-access into a generic event bus. Add only source-proven
material event corrections needed to keep an existing root safe.

### Sports Today must be time-aware

An 08:25 current-day message cannot call every same-day event "upcoming".
Some sport may start early.

Rendering policy under review:

- event starts later -> ordinary `Начало в ...`;
- event has started and a known end is still in the future -> factual
  `Началось в ...` / ongoing presentation;
- event has a known end already in the past -> omit;
- event started earlier but has no known end -> do not invent duration; use a
  neutral `Сегодня с ...` form if still editorially useful;
- all-day/date-only competitions remain eligible.

This avoids both stale "will start" claims and guessed durations.

### Friday weekend planning and Sports Today serve different freshness horizons

Friday's 19:15 weekend digest may describe a Sunday fixture roughly 36-48 hours
before it occurs.

Sunday Sports Today reads the newest accepted same-day source snapshots and is
therefore not redundant. It is the natural current-day correction layer for
late fixture changes without creating a continuous sports monitor.

Mutable future league sources still need a reviewed freshness contract in the
existing morning event refresh. Do not add per-sport morning cron rows.

### Descriptive sports copy increases Telegram size risk

The shared `build_event_section()` stops appending blocks when the 3900-byte
presentation budget would be exceeded. It does not currently surface an
explicit "some events were omitted" condition.

Adding richer sports copy could therefore make a planning/current-day post
silently lose tail events.

New sports publication behavior must not rely on silent truncation.

Preferred invariant:

1. render all eligible sports with rich but bounded blocks;
2. if the complete aggregate does not fit, deterministically remove optional
   prose/teasers while preserving every event's identity, sport, competition
   context, time and place;
3. if it still cannot fit, fail closed in preview/runtime and measure actual
   cardinality before introducing multi-message pagination.

Do not pre-build a multi-message transaction protocol for a volume that has
not been observed.

### Mixed municipal programme grouping needs projection care

A municipal programme can theoretically contain both sport and non-sport
children under one `programme_title`.

Naively splitting the merged Event list into sport/non-sport subsets can cause
the same programme parent to be rendered once in the general section and once
in the sports section.

The sports presentation projection should therefore avoid blindly reusing a
mixed programme parent. If a programme is mixed, render the sports occurrence
as a sports item and retain the programme name only as optional context (for
example, "в рамках ..."). If the whole source-proven programme is sport, normal
programme grouping may remain.

This is presentation-only logic; it does not require a second event identity.

### Source-backed competition stage examples

Official FFCV material confirms that league context is explicit rather than
inferred:

- `Segona FFCV, Grup 8, Temporada 2026-2027`;
- numbered `Jornada` rows.

Official FEPyC event metadata likewise exposes competition type/category for
fishing, e.g. `Tipo Competición: Nacional`, category `Dúos`.

Therefore federation adapters should preserve these fields as readable
competition context rather than reducing every item to only title/date/place.


## Review cycle 3 — runtime, delivery and schedule findings

### Weekend delivery is not crash-safe today

Friday Weekend currently uses the generic `PublicationState`:

1. check `is_published(saturday)`;
2. build message;
3. call `send_message()`;
4. only after confirmed success call `mark_published(saturday)`.

It has no `uncertain` reservation.

Worse, the call currently uses `send_message()` with its default transient
retry behavior rather than `retry_only_rate_limits=True`.

Therefore a timeout/network/5xx after Telegram may have accepted the first
message can cause:

- a same-process retry; and/or
- the scheduled 20:15 Weekend recovery to send another copy because
  `last_successful_date` was never committed.

This is an existing planning-delivery bug. Adding sports to Weekend would
increase the impact; do not add a sports workaround.

The dated crash-safe state abstraction considered for Sports Today now has a
stronger justification: use one small versioned at-most-once dated-publication
primitive for Tomorrow, Sports Today and Weekend, with explicit compatibility
handling for the existing Weekend `last_successful_date` file. This remains
a narrow publication-state reuse, not a generic workflow framework.

New message sends in these planning lifecycles should retry automatically only
explicit HTTP 429 rejection; ambiguous network/5xx failures preserve uncertain
state.

### Exact sports/current-day cron minutes are not final yet

Repository cron installers show a dense recurring minute layout:

- capacity backstop: :12, :27, :42, :57;
- 112: :19;
- Hidraqua: :00 and :30;
- traffic: :37;
- earthquakes: :55;
- guide: 09:02;
- course notices: 09:42 and 11:42;
- transport notice: 08:42;
- SUMA: 08:05;
- later seasonal SafeBeach/monitor windows.

Therefore the earlier candidate times (08:25/09:25 Sports Today and
09:47/10:47 event-access) are **product-window candidates, not accepted cron
rows**.

Before implementation/deploy, inspect the live production crontab and measured
neighboring task durations, then choose staggered minutes. Preserve:

- one primary + one recovery for current-day sport if recovery is retained;
- exactly two event-access checkpoints (move them earlier rather than adding a
  third sports-specific checkpoint);
- Europe/Madrid cron semantics;
- no per-sport schedules.

The architecture depends on the window, not those exact minute values.

### Offline/ambiguous Telegram delivery must prefer no duplicate

The shared Telegram client treats no-status network failures and 5xx as
ambiguous for new-message sends.

Sports Today should follow the same safety policy as Tomorrow/Event Access:
an ambiguous send blocks automatic resend until operator resolution or the next
lifecycle day. Do not add connectivity probes or optimistic resends merely to
improve delivery rate.

This preserves the project's existing "no duplicate after ambiguous send"
contract, even though a phone-offline incident can occasionally cost a
time-sensitive post.

## Review cycle 4 — identity, deduplication and source ownership

### Keep raw source identity separate from editorial team names

Federation adapters should retain stable team/competition IDs and raw official
names inside their source snapshot for identity.

The public Event title may be deterministic editorial Russian such as:

`Футбол — Guardamar против Sporting Saladar`

rather than exposing a sponsor-heavy local source string such as
`GRUPO NEXUS GUARDAMAR`.

Do not build a global club-name rewriting database. Each accepted federation
adapter may have a tiny exact alias map for the known local team IDs/names it
owns. Opponent proper names remain source names unless a reviewed transliteration
rule is necessary.

### Federation competition context should enrich Event.details

Use explicit source fields to construct ordered context strings, e.g.

- `Segona FFCV · группа 8 · 5-й тур`;
- `Кубок ... · полуфинал`;
- `Провинциальный чемпионат Аликанте`;
- `Национальный чемпионат · категория дуэты`.

The 2026/27 official FFCV calendar explicitly identifies Segona FFCV, Group 8
and numbered Jornadas; FEPyC explicitly identifies competition type
`Nacional` and category `Dúos`.

No inference from calendar position is allowed.

### Ordinary Event cross-source dedupe needs one sports guard, not a resolver

Event-access avoids duplicate roots by source ownership **before** global Event
merge. Ordinary city-event dedupe still relies on title/time/place overlap.

For sports, add only the minimum extra safety:

- different known `sport` values can never merge;
- same exact federation source occurrence remains authoritative for competition
  context;
- a municipal/Turismo row may merge with a federation fixture only under the
  existing time/title/place evidence strengthened by source-specific team or
  occurrence evidence when available;
- if identity is ambiguous, keep the federation event and do not use a fuzzy
  cross-source suppression rule that could erase a real second match.

When a second source adds only presentation (poster/venue), enrich after a
deterministic join rather than moving lifecycle ownership.

Do not create a generic canonical-sports-event resolver.

### Municipal SourceEvent eventually needs sport provenance too

Adding `Event.sport` only to FACV/Pesca is enough for the first publication
slice, but future Turismo/municipal mass-sport discovery must preserve the
source-backed sport fact before Event projection.

When that source is enabled, add an optional source-level sport/provenance field
(or an equally narrow source-owned deterministic projection) rather than
reclassifying translated Event titles downstream.

Do not expand the municipal schema in advance of an accepted source contract.

### Access ownership remains explicit with delegated providers

For a mass race discovered/owned by Turismo or the responsible organiser, an
explicit registration platform link does not make the commercial provider the
event owner.

Preferred ownership:

- official event/organiser source supplies the stable event/root identity and
  presentation;
- explicitly delegated timing/registration provider may supply only reviewed
  access action/status/price/deadline facts;
- the provider does not create a second root or independent discovery event.

This is exactly the explicit ownership/delegation rule required by ADR 0091
when the second overlapping access source is enabled.

### Event-access date correction is now a required core completion

ADR 0090 already promises material event-date correction replies, but runtime
does not implement them.

Because v2 state already stores event start/end dates, add the missing date
transition notice to the same event-access planner before relying on photo roots
as canonical long-lived sport cards.

No state-schema expansion is needed for date-only correction detection.

### Cancellation/postponement should stay narrow

Do not turn every ordinary fixture into a long-lived lifecycle root.

For an event that already owns an access root, an explicit responsible-source
cancellation or postponement is material enough that leaving the detailed root
unqualified would be misleading. A narrow rooted-event correction should be
supported when a real source contract supplies that status.

For ordinary matches without an access root, current planning/Sports Today
freshness should simply omit or label the fixture from the current federation
state. Do not create a generic cancellation monitoring daemon.

Time/place corrections beyond date changes require a real source contract and
a separate bounded design review; do not silently claim that current event-
access state already handles them.
