# Sports events implementation plan — 2026-10-05

## Status

Draft v1. This plan is intentionally implementation-free and will be revised
through adversarial review cycles before it is considered ready.

Base production architecture reviewed at:

- `main = d63807751fab0c08656748714ec1ab78d3739765`;
- stabilized source/product research:
  `research/2026-10-05-sports-event-publication-architecture-review.md`;
- ADRs 0080 and 0089-0092;
- current runtime/cron constraints in KB 03-04.

ADR 0099 is already allocated to hourly AEMET CAP monitoring, so the next
durable sports architecture decision should use **ADR 0100** unless main moves
again before implementation.

No production code or runtime state is changed by this planning document.

---

## 1. Product target

One real sporting event remains one semantic event. It may have several
resident-facing projections serving different decisions:

```text
official source facts
        |
        +--> event-access root + strict lifecycle replies
        |
        +--> "tomorrow" / Friday weekend planning section
        |
        +--> standalone "sports today" reminder/correction
        |
        +--> Morning Digest: excluded once Sports Today is live
```

The intended resident lifecycle is:

1. when actionable registration/reservation/ticket access appears, publish one
   detailed event root, preferably with one exact official event image;
2. later access changes reply to that root;
3. the event appears in the existing planning surface before the day;
4. it appears again in a dedicated current-day sports message;
5. sports are not repeated in Morning Digest.

The planned-day and current-day mentions are intentional, not duplicate
delivery.

---

## 2. Non-negotiable architecture invariants

The implementation must preserve all of these:

1. No separate sports database, daemon, generic crawler, browser worker or
   background scheduler.
2. No sports-specific registration lifecycle. Reuse event-access v2.
3. No global fuzzy cross-source sports ownership resolver.
4. No title-keyword classifier as the authoritative sports classifier.
5. No runtime AI for sports publication or access delivery.
6. No per-sport cron rows. Source refreshes remain grouped in bounded existing
   refresh lifecycles.
7. No automatic inference that "home team" means the venue is in Guardamar.
8. No guessed free admission, duration, cancellation, stage or registration
   status.
9. No silent event loss because a long Telegram section hit the renderer limit.
10. No automatic duplicate after ambiguous Telegram send.
11. No broad source precedence engine. Source authority remains fact-specific.
12. No state-schema migration merely to add presentation fields such as sport,
    title, details or image URL.
13. Python 3.9 compatibility and current standard-library-first constraints
    remain mandatory.

---

## 3. User-facing information contract

A sports item should answer the useful questions supported by the source:

- sport;
- participants/teams or participation form;
- competition/division;
- group;
- round/jornada or explicit knockout/qualifying/friendly stage;
- useful category such as senior/youth or men/women when it distinguishes the
  actual team/event;
- start/end/schedule;
- venue;
- distance/format;
- official time limit or source-known duration;
- current ticket/registration information when safe and current.

Example shape:

```text
⚽ Футбол — Guardamar A против Sporting Saladar
Segona FFCV · группа 8 · 5-й тур
🕐 18:30
📍 Campo Municipal Les Raboses
```

Do not call a match a qualifier, friendly, semi-final or final unless the
responsible source says so.

Sponsor-heavy federation team names remain raw source identity but may have a
small exact source-specific public alias for the known local side. Squad/category
suffixes that distinguish real teams must not be erased.

For multi-distance events, never store bare parallel distance details that the
shared renderer could collapse. Use labelled facts such as:

- `Полумарафон: 21,097 км · лимит времени 2 ч 30 мин`;
- `10K: 10,5 км · лимит времени 1 ч 30 мин`.

---

## 4. Dependency graph

```text
A. planning delivery safety
        |
B. Event.sport + merge/presentation foundation
        |
C. Pesca/FEPyC occurrence correctness gate
        |
D. planning renderer/read foundation
        |
E. sports sections + Sports Today + Morning exclusion
        |
F. generic event-access completion
        |
G. Pesca access + multi-source event-access + earlier access window
        |
H. FVBCV
        |
I. FFCV
        |
J. Turismo mass sport + delegated registration
        |
K. further sport sources one-by-one
```

A and B may be developed independently, but **E must not be activated before
A, B and C are complete**.

F may be developed in parallel with D/E, but G depends on F and C.

---

# Slice A — crash-safe dated planning delivery

## Goal

Fix the existing Weekend ambiguous-delivery bug and create the exact small
at-most-once primitive Sports Today will need, without changing sports product
behavior.

## A1. Extract one shared dated-delivery state primitive

Introduce a small internal state class, conceptually
`DatedPublicationState`, with the already-proven Tomorrow semantics:

```text
version
target_date
status = uncertain | sent
message_id            # sent only
```

Required operations:

- status(target_date);
- mark_uncertain(target_date);
- clear(target_date);
- mark_sent(target_date, message_id);
- non-blocking exclusive_run();
- atomic fsync + replace;
- strict validation.

Do not create a generalized workflow/scheduler framework.

## A2. Preserve Tomorrow compatibility

Refactor `TomorrowEventState` onto the shared primitive while preserving:

- existing `state/tomorrow_events.json` format;
- existing environment/path names;
- existing CLI behavior;
- existing import name/tests through a compatibility alias or thin wrapper.

There must be zero Tomorrow state migration.

## A3. Fix Weekend without making rollback unsafe

Do **not** overwrite `state/weekend.json` with the new schema because old
production code expects the legacy
`{"last_successful_date":"YYYY-MM-DD"}` layout.

Use a separate bounded crash-safe delivery file, for example:

`state/weekend_delivery.json`

with an optional environment override.

Keep the existing legacy Weekend `PublicationState` as a rollback marker.

Weekend runtime order:

1. acquire the new dated-delivery lock;
2. if the legacy Weekend marker already says this target Saturday was
   published, skip;
3. if new delivery state is `sent`, skip;
4. if new delivery state is `uncertain`, fail closed and skip;
5. build the complete Weekend message;
6. mark new delivery state `uncertain`;
7. send with `retry_only_rate_limits=True`;
8. deterministic unsent failure -> clear new uncertain state, leave legacy
   marker untouched so recovery may retry;
9. ambiguous failure -> keep uncertain, no automatic retry/recovery duplicate;
10. confirmed Telegram success -> write the legacy Weekend success marker;
11. then mark the new delivery state `sent` with Telegram message ID.

If the post-send legacy marker write fails, leave the new delivery state
uncertain and require operator reconciliation before rollback. Never resend
automatically after a confirmed Telegram success.

Keep dual-write rollback compatibility through the sports rollout; do not
schedule cleanup of the old marker in the same project.

## A4. Tests

Add/adjust tests for:

- Tomorrow state byte/schema compatibility;
- Weekend legacy marker suppresses a same-target resend;
- confirmed Weekend send writes legacy marker then sent delivery state;
- deterministic Telegram failure clears uncertain;
- explicit 429 may retry safely;
- timeout/network/5xx remains uncertain;
- 20:15 recovery is a no-op after sent or uncertain;
- state-write failure after Telegram success cannot cause an automatic resend;
- installer behavior remains idempotent.

## A5. Deployment gate

Deploy this slice independently before changing Weekend content.

Production verification:

- backup/inspect both Weekend state paths;
- preview creates no state;
- no Telegram post is sent during deploy;
- verify old Friday state is still readable;
- a controlled non-sending/state unit probe must exercise sent/uncertain
  transitions immediately;
- before Slice E relies on Weekend for sports, verify at least one normal
  Friday publication or an equivalent production-safe delivery simulation.

Rollback remains safe because old code still sees the legacy marker. If a
confirmed Telegram send is followed by a legacy-marker write failure, do not
roll back until that marker has been reconciled manually; the new uncertain
state prevents an automatic duplicate in the meantime.

---

# Slice B — explicit sport identity and merge foundation

## Goal

Carry source-owned sport identity through the existing Event model without
changing resident-facing routing yet.

## B1. Add only `Event.sport`

Add:

```python
sport: Optional[str] = None
```

at the **end** of the Event dataclass to preserve positional-call compatibility.

Do not add a global Competition model or fields for round/stage/team IDs now.

## B2. Existing source projections

Set:

- FACV Event -> `sport="chess"`;
- Pesca CV Event -> `sport="fishing"`.

Their raw snapshots already store these facts, so this adds no source request
and no source-state migration.

## B3. Merge rules

Before ordinary fuzzy duplicate matching:

- known sport A + known different sport B -> cannot merge;
- sport + None -> may merge under normal identity evidence and resulting Event
  preserves the known sport;
- same sport + same sport -> ordinary merge rules continue.

When two events merge, preserve `current.sport or candidate.sport`.

Add sports-specific regression cases without replacing existing municipal /
Agenda merge rules.

## B4. Presentation helper

Add one small deterministic sports-presentation helper/module that owns:

- canonical sport code -> Russian label/icon;
- presentation-only event decoration;
- no source access;
- no state;
- no AI.

The source adapter, not the global helper, remains responsible for:

- raw team IDs;
- exact local-team aliases;
- competition context;
- source-specific status semantics.

## B5. Tests

Cover:

- old Event construction still works;
- FACV/Pesca sport survives projection;
- None + sport merges to sport;
- different known sports never fuzzy-merge;
- same-sport existing federation/municipal dedupe still works;
- sport presentation does not mutate source identity.

No Morning/Tomorrow/Weekend routing changes occur in this slice.

---

# Slice C — fishing occurrence correctness before sports activation

## Goal

Make the known FPCV/FEPyC national-date conflict impossible to publish as a
false day-by-day sports claim.

## C1. Production source probe first

Before implementation, probe the current official FEPyC browserless contract
for:

- Guardamar national competitions;
- stable event identity/code;
- exact start/end dates;
- content type;
- redirect policy;
- response size/time;
- update/cancellation semantics if exposed.

Record the probe in `research/`.

## C2. Preferred implementation

If one stable bounded official HTML contract exists:

- add one small FEPyC national competition source;
- refresh it inside the existing 05:10 event-source wrapper;
- retain only current/future Guardamar national competition facts;
- use source-owned FEPyC identity and exact dates;
- suppress/replace only deterministically joined FPCV `NACIONAL` occurrence
  dates for the same national event;
- keep FPCV local/regional organization/access facts available for enrichment.

No generic priority system.

## C3. Fail-closed fallback

If the FEPyC live contract cannot be proven safely:

- do not publish ambiguous FPCV national ranges in sports surfaces;
- keep provincial/autonomous verified FPCV events;
- document the national row as withheld until authoritative dates are
  available.

Wrong dates are worse than incomplete sports coverage.

## C4. Required regression

The November 2026 Mar Costa Dúos case must not produce championship occurrence
days on 23-25 November when FEPyC says 26-29 November.

## C5. Tests/runtime

- bounded request and source validation;
- deterministic overlap/suppression;
- source failure preserves last-good accepted facts but never invents date
  authority;
- no browser/OCR/AI;
- 05:10 wrapper still remains one short-lived sequential source-preparation
  process.

---

# Slice D — shared local planning read and complete rendering

## Goal

Avoid copying Tomorrow's local-source loading into Sports Today and make sports
planning incapable of silently dropping tail events.

## D1. Extract only the common local read needed

Create a small explicit helper for **local snapshot -> merged events for one
target day**, shared by Tomorrow, Weekend and Sports Today.

This is justified not only by reuse but by freshness safety: the Friday
`run-weekend.sh --fresh` wrapper refreshes Municipal/FACV/Pesca, Agenda and
CONVEGA before the 19:15 primary run, while the 20:15 recovery intentionally
reuses those local snapshots. The renderer must verify the Friday observation
date rather than blindly turning an older last-good sports snapshot into a
current weekend claim.

The helper should retain explicit arguments/source calls rather than a generic
plugin registry.

It must support:

- target datetime/day;
- required snapshot observation day for proactive/current claims;
- current paths for Municipal, Agenda, Library, AM Guardamar, FACV, Pesca,
  CONVEGA;
- existing source-specific error handling;
- `_prefer_agenda_guardamar_venues`;
- existing `_merge_events`.

No network and no AI.

Weekend passes `include_recurring=True` (or an equally small explicit
parameter) so its existing recurring market/Campo behavior is preserved.
Tomorrow/Sports Today do not gain unrelated recurring facts merely because the
loader is shared.

The helper must preserve source-specific timestamp fields and diagnostics.
Do not turn the explicit source list into a registry/plugin framework.

## D2. Complete-section rendering

The current `build_event_section()` may silently stop when the 3900-character
budget is reached.

Add a narrow shared complete-render path, for example
`build_complete_event_section()`, reusing the same underlying event block
renderer but failing rather than silently omitting a block.

Keep the existing truncating helper behavior for unrelated existing callers
unless they are explicitly migrated.

Planning surfaces using sports must obey:

1. preserve every eligible event;
2. remove optional teaser/prose first when necessary;
3. preserve sport, identity, competition context, time and place;
4. if the complete aggregate still cannot fit, fail closed and log/preview the
   size problem;
5. do not implement pagination/multi-message transaction until real measured
   volume requires it.

## D3. Essential context placement

Competition/division/group/round/stage must live in title/details, not only in
`teaser`, because multi-event Tomorrow currently drops teasers.

## D4. Multi-distance safety

Add tests proving labelled race-distance details are not collapsed by
`_normalized_event_details()`.

Do not change the generic route-distance normalization semantics merely for one
race source.

---

# Slice E — activate sports planning + Sports Today

## Goal

Deliver the requested resident product using corrected existing sources before
adding league sources.

This is the first user-visible sports publication slice.

## E1. Tomorrow sports subsection

Keep the existing `Завтра в Гуардамаре` lifecycle and schedule.

Split eligible merged events into presentation groups after merge:

- non-sport;
- sport.

Render one planning message with a clear sports subsection, e.g.
`🏅 Спортивные мероприятия`.

Do not create a separate evening sports message or cron.

Friday/Saturday Tomorrow suppression remains unchanged.

Image rule remains:

- one official image only when the **whole** publication resolves to one
  editorial unit and the image passes the existing approved contract;
- multi-event planning remains text;
- do not broaden the image host allowlist speculatively for federations.

## E2. Friday Weekend sports subsection

Inside each Saturday/Sunday block, render:

- ordinary city events;
- a clearly separated sports subsection when sport exists.

For mixed municipal programmes:

- do not render the same programme parent twice;
- sports children may be flattened into the sports subsection with the
  programme name retained only as optional context;
- wholly sporting source-proven programmes may remain grouped.

Weekend uses the crash-safe delivery from Slice A.

## E3. Standalone Sports Today

Add one local-only command/publication, conceptually:

- `sports-today`;
- `sports-today-preview`.

It reads only fresh accepted local snapshots and performs zero source HTTP and
zero AI.

Suggested state path:

`state/sports_today.json`

using the shared dated-delivery primitive.

User-facing header:

`🏅 Спортивные мероприятия сегодня — <date>`.

No qualifying sport -> no message and no sent marker.

### Time-aware current-day eligibility

- starts later -> `Начало в HH:MM`;
- started and known end is future -> factual ongoing presentation;
- known end is already past -> omit;
- started earlier and end unknown -> neutral `Сегодня с HH:MM`, never guess
  duration;
- date-only/all-day competitions remain eligible if the source proves the day.

## E4. Morning exclusion

In the **same release/deploy** that installs and verifies Sports Today:

- Morning Digest stops rendering events with `sport is not None`.

Do not land/deploy the Morning exclusion ahead of Sports Today.

## E5. Multi-day contract

Do not use a global rule that every sporting date range is active daily.

Each adapter determines whether its range means:

- source-proven activity every day; or
- only a broad event period.

Sports Today shows only source-proven current-day occurrences.

## E6. Sports Today delivery/recovery schedule

Do not hard-code the previously discussed 08:25/09:25 minutes in design.

Before final cron patch:

1. inspect live production `crontab -l`;
2. inspect recent task durations/logs around 08:00-11:00;
3. select one primary + one recovery slot with safe staggering;
4. keep `CRON_TZ=Europe/Madrid`;
5. add both rows inside the existing event-planning/weekend managed cron block,
   not a new per-sport installer.

The runner is a short-lived one-shot and needs no runtime source lock because it
reads local snapshots and sends Telegram only.

## E7. Current-day cancellation correction

The first source that exposes explicit cancelled/postponed occurrence state must
preserve it.

Sports Today must be able to say, from current responsible-source evidence:

- match/event cancelled;
- match/event moved to a known new date.

Do not merely omit a fixture that was previously announced in Weekend/Tomorrow
when the source explicitly says it is cancelled.

Do not add a global Event status field in Slice B. Add the minimum explicit
status representation only with the first accepted source contract that needs
it.

## E8. Tests

At minimum:

- sports subsection in Tomorrow;
- sports subsection by day in Weekend;
- Friday/Saturday Tomorrow suppression unchanged;
- Morning excludes sport only in final product path;
- Sports Today current-day rendering;
- already-ended event omission;
- ongoing/unknown-end wording;
- no sport -> no message/state;
- confirmed primary -> recovery no-op;
- uncertain -> recovery blocked;
- different sport events all remain present;
- mixed programme does not duplicate parent;
- complete rendering never silently drops a sport;
- first/final generic range behavior remains for non-sport;
- source-proven multi-day sport behavior is adapter-tested.

---

# Slice F — complete generic event-access v2 before sports access rollout

## Goal

Finish the already accepted generic architecture so sports sources plug into it
without a parallel mechanism.

No persistent v2 state migration is required for the changes below unless a
later source-specific status fact explicitly requires one.

## F1. Access-kind-correct language

Make all root/reply wording depend on `access_kind`:

- registration;
- reservation;
- ticket.

Cover:

- open/reopened/closed;
- opening tomorrow/today;
- closing tomorrow/today;
- deadline known/changed;
- action changed;
- one-day access where relevant.

The existing action labels (`Записаться`, `Забронировать`,
`Получить билет`) remain aligned.

## F2. Implement the ADR 0090 event-date correction

Current v2 state already stores event start/end dates.

When an audience-known event with a root changes date/range:

- compare previous vs current event date/range before committing candidate;
- create one material date-correction reply to that same root;
- render the new date explicitly;
- combine with any stronger same-observation access change into **one reply**
  where practical rather than send multiple messages;
- no separate trigger history is required solely for date changes because
  committed state itself becomes the dedupe baseline;
- if no root/audience exists, silently adopt current date until the first
  useful root.

Add precedence tests for date + access change in one observation.

## F3. Implement photo roots, text replies

Add optional presentation-only `image_url` to `EventAccessRecord`.

Do not persist it in event-access semantic state and do not bump state version.

Root delivery:

1. source adapter validates one exact event-specific official image;
2. reserve the existing uncertain root transaction;
3. if complete root fits photo caption limit, call `send_photo_url()`;
4. explicit deterministic remote-photo rejection -> send the exact same card as
   text under the same logical reserved transaction;
5. ambiguous photo failure -> propagate ambiguity; no text fallback;
6. confirmed send -> store returned root message ID;
7. replies remain text-only strict replies;
8. if card does not fit caption, send one complete text root;
9. never create a second root merely because an image appears later.

No `file_id` needs to be stored because roots are not edited.

## F4. Root correction responsibility

For rooted events, explicit responsible-source cancellation/postponement is a
material correction and must outrank a weaker access-only statement such as
"registration closed".

Do not introduce generic cancellation state until an enabled source proves the
contract. The core must be designed so the first such source can produce one
root correction without a second lifecycle.

## F5. Tests

Add:

- registration/reservation/ticket wording matrix;
- date change root reply;
- no date reply before audience/root;
- same observation date + access change -> one coherent publication;
- photo root success stores root ID;
- deterministic photo rejection -> text fallback;
- ambiguous photo failure -> uncertain, no text duplicate;
- >1024 root -> complete text root;
- image changes do not create lifecycle changes;
- replies remain strict and poster-free.

---

# Slice G — FPCV access + second event-access source + access-time correction

## Goal

Use the real 17 October Guardamar fishing case to prove the multi-source
event-access path without a generic source framework.

## G1. ADR/runtime permission for FPCV convocatoria PDF

Before code, amend the accepted docs to allow exactly the reviewed FPCV
convocatoria contract:

- exact official linked PDF only;
- bounded bytes;
- text-layer extraction with existing Termux `pdftotext`;
- no OCR/image rendering/browser;
- parse only required facts;
- no raw PDF archive;
- normalized last-good facts only;
- bounded number of relevant Guardamar documents per refresh.

Do not silently expand the generic Poppler permission.

## G2. Production probe and bounds

Probe:

- convocatoria index -> exact PDF link relationship;
- MIME/redirect/size;
- whether stable link/content identity exists;
- whether conditional metadata/ETag can avoid unnecessary text extraction;
- exact wording for registration audience/deadline;
- cancellation marker semantics.

Choose explicit max documents/bytes/time from measured source behavior.

## G3. Keep one source snapshot boundary

Prefer extending the existing Pesca normalized source snapshot with optional,
strictly validated access/enrichment fields while retaining backward
compatibility with old snapshots.

Do not invalidate the entire last-good v1-like Pesca snapshot merely because
new optional access facts are absent.

If the safest implementation needs a separate normalized convocatoria section,
keep it within the same Pesca source state rather than introducing another
independent cron/state lifecycle.

## G4. One raw source observation -> two projections

From the same accepted normalized Pesca facts produce:

- normal `Event` for planning/current day;
- `EventAccessRecord` for advance registration lifecycle.

Do not parse the PDF independently in the access runner.

For the 17 October case preserve:

- sport = fishing;
- provincial Alicante championship;
- qualification meaning;
- exact competition schedule/heat duration;
- club-mediated registration;
- exact deadline;
- place/zone;
- current cancellation state if explicitly published.

## G5. Multi-source access orchestration

Current runtime is CONVEGA-only.

With Pesca as the second source, introduce only a small explicit source-batch
orchestrator:

- CONVEGA loader + its freshness;
- Pesca loader + its freshness;
- deterministic record ordering;
- existing single global uncertain outbound slot;
- no plugin registry;
- no dynamic source discovery;
- no generic ownership resolver.

Source ownership remains explicit.

## G6. Move the two event-access checkpoints earlier

The existing 12:47/13:47 window cannot send a useful same-day reminder before a
known 12:00 deadline.

Do **not** add a third sports access cron.

Before choosing exact replacement minutes:

1. inspect live production crontab;
2. inspect neighboring task durations;
3. ensure first checkpoint occurs early enough for reviewed midday deadlines;
4. keep one recovery/checkpoint later without creating a request storm;
5. re-evaluate CONVEGA <=90-minute freshness with the chosen spacing;
6. document whether recovery can reuse the first snapshot or may perform one
   additional bounded refresh.

The final schedule belongs to the shared event-access lifecycle, not to Pesca.

Exact minute values are an implementation/deploy decision, not fixed by this
plan.

## G7. Tests

- club-mediated wording does not imply direct public self-registration;
- closing-tomorrow and closing-today before exact deadline;
- no closing-today after deadline;
- Pesca source failure cannot promote stale access truth;
- CONVEGA behavior remains unchanged;
- one ambiguous source record publication blocks later record sends exactly as
  current v2;
- second source does not create duplicate root for deterministically delegated
  same event.

---

# Slice H — FVBCV volleyball source

## Gate

Do not implement before a production read-only probe proves:

- official browserless HTML/JSON endpoint;
- bounded response;
- stable team/fixture identity;
- competition/division/group/jornada fields;
- current date/time;
- physical venue/location;
- postponed/cancelled/withdrawn semantics.

If physical Guardamar venue cannot be proven, do not automate the fixture.

## Implementation

- one bounded official source adapter;
- refresh inside the existing pre-morning event refresh, not a new cron;
- raw official team IDs/names retained in source snapshot;
- exact small alias map only for known local team identity;
- `sport="volleyball"`;
- readable Event title;
- competition context in ordered details;
- publish only physically Guardamar fixtures accepted by the source contract;
- no scores/standings/results publication.

If the source status contract justifies a minimal Event status representation,
add it here with exact tests; do not generalize beyond observed statuses.

Sports Today becomes the same-day correction surface for explicit
cancelled/postponed fixtures.

---

# Slice I — FFCV football source

## Gate

Do not use the static season PDF as final live fixture truth.

Production probe must find an official current HTML/JSON contract that can
prove:

- stable fixture/team/competition identity;
- competition/division/group;
- jornada or explicit knockout stage;
- date/time;
- physical venue in Guardamar;
- current suspended/postponed/cancelled state.

The season PDF may be background/fallback research only, not the automated live
publication authority.

## Implementation

Same architecture as FVBCV:

- bounded official adapter;
- existing pre-morning refresh;
- exact local team aliases preserving A/B/category identity;
- `sport="football"` or `futsal` according to source;
- no scores/standings;
- source-backed competition context.

---

# Slice J — Turismo mass participation sport + delegated registration

## Gate

Probe an official Turismo/Ayuntamiento sports discovery contract:

- stable sport category/provenance or another deterministic first-party
  classification;
- event-specific image;
- date/time/place;
- distances/format;
- useful participation facts;
- explicit external registration delegation when present.

Do not classify arbitrary municipal titles by keywords.

## Event ownership

The official event/organiser source owns:

- event identity;
- title/presentation;
- image;
- occurrence/date/place.

An explicitly delegated registration/timing provider may supply only reviewed:

- action URL;
- deadline;
- price;
- capacity/availability.

The commercial provider never becomes an independent event-discovery feed or
second Telegram root.

## Event/access projections

Build Event and EventAccessRecord from one joined accepted occurrence.

Reuse the generic photo-root and access lifecycle completed in Slice F.

Do not add price-change monitoring unless a real resident requirement/source
contract later justifies it.

---

# Slice K — further sport coverage

After the foundation is proven in production, evaluate official sources
one-by-one for:

- basketball;
- tennis;
- cycling;
- triathlon;
- swimming/open-water;
- sailing/regattas;
- kayak/SUP;
- other municipal/federation sport.

Every new adapter must pass the same acceptance checklist:

1. physically relevant to Guardamar;
2. official/responsible source;
3. browserless bounded contract;
4. stable occurrence identity;
5. date/time;
6. venue/locality;
7. competition context;
8. cancellation/postponement behavior where applicable;
9. access ownership when registration/tickets exist;
10. no new per-sport daemon/cron/database.

Do not create a generic provider framework in anticipation of these sources.

---

# Documentation plan

When implementation begins, record durable decisions before/with the relevant
runtime change:

## ADR 0100

Create a new accepted ADR for:

- Event.sport;
- sports subsections in Tomorrow/Weekend;
- standalone Sports Today;
- Morning exclusion;
- source-backed competition context;
- current-day correction semantics;
- no separate sports subsystem;
- source onboarding constraints.

## Update ADR 0080

Document:

- Weekend/Tomorrow crash-safe planning delivery;
- no silent partial sports planning output.

## Update ADRs 0090-0092 implementation notes

Record completed generic gaps:

- access-kind wording;
- event-date correction;
- photo roots;
- multi-source explicit orchestration;
- changed shared access checkpoint window.

Do not rewrite historical decisions; add refinement/implementation notes.

## KB/README

Update as slices land:

- KB 03 lifecycle inventory;
- KB 04 runtime/PDF/cron constraints;
- KB 05 features;
- KB 06 data sources;
- KB 10 decision log;
- README commands/state/cron examples.

Time-sensitive provider probes remain in `research/`.

---

# Cross-slice testing strategy

Every implementation PR must run focused tests plus the full repository suite.

Required focused areas:

- `test_event_contract.py`;
- `test_event_merge_regression.py`;
- `test_federation_event_pipeline.py`;
- `test_universal_event_details.py`;
- `test_digest.py`;
- `test_tomorrow_events.py`;
- `test_weekend.py`;
- `test_termux_weekend.py`;
- new Sports Today tests;
- `test_event_access.py`;
- `test_event_registration_notifications.py`;
- `test_facv.py`;
- `test_pesca_cv.py`;
- future source-specific tests;
- Telegram delivery-policy tests.

Before each production deployment:

1. `python -m compileall` on changed modules;
2. focused suite;
3. full suite;
4. production preview/read-only probe where source/runtime-specific behavior is
   involved;
5. no Telegram/state mutation during preview.

---

# Deployment sequencing

## Deployment 1 — delivery foundation

Slice A only.

No sports behavior change.

Observe one real Weekend lifecycle before relying on it for richer sports.

## Deployment 2 — sport model/source correctness foundation

Slices B + C.

No Morning removal yet.

Run Tomorrow/Weekend previews and verify sport identity/dedup, but resident
output may remain unchanged until Slice E.

## Deployment 3 — sports resident product

Slices D + E.

Atomic operational requirements:

- Sports Today command and state present;
- chosen cron primary/recovery installed and verified;
- Tomorrow/Weekend sports sections preview correctly;
- Morning sport exclusion becomes active only now;
- no source network added by Sports Today.

## Deployment 4 — generic Event Access completion

Slice F.

Do not add Pesca access until photo/date/wording behavior is fully tested.

## Deployment 5 — Pesca access and shared checkpoint move

Slice G.

Requires live crontab preflight and FPCV PDF/source production probe.

## Deployments 6+

FVBCV, FFCV, Turismo/mass sport and later sources one adapter at a time.

Do not bundle several unproven providers into one deployment.

---

# Rollback boundaries

## Slices A-E

No semantic event-access state schema change.

- Event.sport is presentation/runtime-only;
- source snapshots remain backward-compatible;
- Sports Today has independent state;
- Weekend legacy marker remains current for old-code rollback.

Rollback to prior code is safe after stopping/removing the new Sports Today cron
rows.

## Slice F

Photo/image is not persisted and event-access state remains v2.

Event-date correction uses existing date state.

Rollback is safe at the state-schema level, but after new resident-facing root
or reply history has been sent, do not intentionally replay older code that
would contradict trigger/root history. Prefer forward fix for publication
logic bugs.

## Slice G+

Source snapshots must remain backward-readable or have an explicit rollback
procedure before deploy.

Do not bump a strict source snapshot schema in a way that makes the previous
production commit unable to read the last-good file unless a reversible
migration/backup is part of the deploy.

---

# Production preflight required before final cron patch

The plan intentionally does not freeze exact new minutes.

Before implementing the cron patch, collect from production:

- complete `crontab -l`;
- current managed block boundaries;
- recent runtime durations around candidate morning windows;
- state of crond/service environment;
- current event-access state version/uncertainty;
- current Weekend/Tomorrow/Sports Today state paths;
- current source freshness times.

Then select exact minute slots and record them in ADR/KB/README/tests.

No plan revision may add a new recurring source job merely to solve minute
placement.

---

# Definition of done for the whole initiative

The initiative is complete when all of the following are true:

1. sports are explicitly classified from source-backed facts;
2. Morning no longer repeats sport;
3. Tomorrow/Weekend contain a readable sports subsection;
4. Sports Today publishes one complete current-day sports message when useful;
5. sports items clearly explain sport, participants, competition level/stage,
   schedule and venue when source-backed;
6. no event is silently truncated from a sports aggregate;
7. Weekend/Tomorrow/Sports Today cannot automatically duplicate after ambiguous
   Telegram sends;
8. event-access handles registration/reservation/tickets with correct wording;
9. event-access roots may use one safe official event image;
10. access date changes reply to the existing root;
11. explicit source-backed cancellation/postponement is surfaced in the
    appropriate current-day/root correction path;
12. the 12:47 deadline gap is removed by one shared earlier event-access window;
13. FPCV national dates cannot override authoritative FEPyC championship dates;
14. FPCV convocatoria access uses bounded approved text-PDF extraction only;
15. FVBCV/FFCV are enabled only after current live source contracts prove
    locality and status semantics;
16. no browser, new daemon, database, queue, generic sports framework or
    per-sport cron exists;
17. every source addition has focused tests, full-suite pass and documented
    source/runtime contract;
18. production deploy and rollback procedures are documented and tested.



---

## Plan review cycle 1 — dependency / freshness / rollback

### Findings

1. **Weekend freshness was underspecified.** The real 19:15 wrapper runs
   `sync-municipal-events.sh`, `sync-agenda-events.sh` and
   `sync-convega.sh`, but the current Weekend reader itself does not enforce
   same-Friday freshness. Rich sports planning must not publish an older
   last-good fixture as if it were freshly verified.
2. **The FEPyC/Pesca gate applies to every planning surface**, not only Sports
   Today. Tomorrow/Weekend could otherwise publish the same known 23-25
   November false national occurrence.
3. Waiting a full week after Slice A is not a code dependency. The plan now
   requires immediate controlled state/delivery verification and a real or
   equivalent production-safe Weekend validation before Slice E relies on it.
4. Weekend rollback safety requires retaining the legacy marker. A rare
   post-send legacy-marker write failure explicitly blocks rollback until
   operator reconciliation.

### Corrections made

- Slice D now shares the explicit fresh local loader with Weekend too, while
  preserving recurring-event semantics.
- Slice C is now an explicit prerequisite for all sports planning output.
- Slice A verification/rollback wording is tightened.

### Result

No remaining dependency-cycle or rollback blocker found in this review.
