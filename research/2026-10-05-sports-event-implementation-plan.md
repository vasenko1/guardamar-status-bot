# Sports events implementation plan — 2026-10-05

## Status

**Stabilized after eight adversarial plan-review cycles. ADR 0100 is now accepted on the implementation branch; Slice A is the next implementation stage.**

This plan remains implementation-free: the architecture-fixation stage changes
only documentation, not production code, cron or runtime state. Any later change to a dependency,
source contract or current main requires a targeted delta review before the
affected slice begins.

Base production architecture reviewed at:

- `main = d63807751fab0c08656748714ec1ab78d3739765`;
- stabilized source/product research:
  `research/2026-10-05-sports-event-publication-architecture-review.md`;
- ADRs 0080 and 0089-0092;
- current runtime/cron constraints in KB 03-04.

ADR 0100 is now the accepted durable sports architecture decision. Later
source/runtime refinements use new ADR numbers only when they materially change
that accepted boundary.

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
14. Any lifecycle/root `record_id` must survive changes to date, time, venue,
    action URL and display title. Never derive root identity from mutable
    scheduling/presentation facts.

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

# Slice C — fishing authority + rich source details before sports activation

## Goal

Make the known FPCV/FEPyC national-date conflict impossible to publish and
prepare sufficiently rich fishing facts **before** the first Sports Today /
Tomorrow sports rollout.

This slice deliberately normalizes the FPCV convocatoria once so the same
accepted facts can later feed both Event presentation and Event Access. Do not
parse the PDF twice in separate lifecycles.

## C1. Production source probes first

Probe two current official contracts:

### FEPyC

Verify the browserless contract for:

- Guardamar national competitions;
- stable event identity/code;
- exact start/end dates;
- competition type/category;
- content type;
- redirect policy;
- response size/time;
- update/cancellation semantics if exposed.

The 2026-10-05 web recheck still exposes first-party event `26MC26` with
Dúos/Nacional/Guardamar and exact 26-29 November dates. Termux verification is
still mandatory.

### FPCV convocatoria/details

Verify:

- competition/index -> exact official convocatoria PDF relationship;
- MIME/redirect/size;
- stable link/content identity;
- text-layer quality;
- competition level/qualification wording;
- schedule/heat duration;
- audience/registration/deadline;
- cancellation marker semantics;
- measured bound on relevant Guardamar documents.

Record both probes in `research/`.

## C2. Explicit runtime permission for the FPCV PDF

Before code invokes Poppler for this source, amend ADR/Runtime Constraints to
allow exactly:

- official linked FPCV convocatoria documents;
- bounded bytes/document count;
- existing Termux `pdftotext` only;
- no OCR/image rendering/browser;
- parse only reviewed facts;
- no raw PDF archive;
- text extraction only when the reviewed document identity/content changed.

Do not silently broaden generic PDF permission.

## C3. FEPyC national occurrence authority

If the production probe confirms the current stable contract:

- add one small FEPyC national authority snapshot;
- refresh it inside the existing 05:10 event-source wrapper;
- retain only current/future Guardamar national facts;
- use source-owned identity (for example the stable competition ID) and exact
  dates;
- consume that snapshot as a **source-specific authority input inside the
  fishing projection**, not as a second parallel generic Event that must later
  be fuzzy-merged;
- deterministically suppress/replace only matching FPCV `NACIONAL`
  occurrence dates;
- keep FPCV local/regional organization/details available for enrichment.

If the FEPyC contract cannot be proven safely, fail closed: withhold ambiguous
FPCV national ranges from sports surfaces while retaining verified
provincial/autonomous events.

No generic source-priority system.

## C4. New rollback-safe FPCV details snapshot

Keep the existing strict `state/pesca_cv_events.json` unchanged so old code
can still read it.

From the **same** existing 05:10 fishing preparation flow, write one new
bounded normalized file, for example:

`state/pesca_cv_details.json`

It may contain only deterministic joins for current/future relevant Guardamar
competitions and reviewed facts such as:

- source/event identity needed for the join;
- official convocatoria URL/content identity;
- competition context;
- qualification meaning;
- schedule/heats;
- source-known duration/time limits;
- audience/registration boundary/action facts;
- explicit cancellation status when published;
- `observed_at`.

Calendar success and details/PDF success are independent:

- base calendar refresh may succeed even when details extraction fails;
- details failure preserves last-good details;
- old production code ignores the new file, so rollback remains safe.

## C5. Enrich the normal Event projection now

Before sports publication is activated, make
`fetch_today_pesca_cv_events(...)` (or one equally narrow fishing projection)
accept/read the FEPyC authority snapshot and `pesca_cv_details.json` through
backward-compatible optional paths, then perform one deterministic
source-specific join.

Do not emit FEPyC and FPCV as two independent generic Events and ask
`_merge_events()` to decide authority later.

For the reviewed 17 October case, preserve source-backed context equivalent to:

- provincial Alicante championship;
- qualifying meaning for Comunidad Valenciana 2027;
- two heats of three hours;
- exact schedule;
- Guardamar beach zones.

Registration/access facts may be present in the normalized details source, but
proactive lifecycle publication still waits for Slice G.

Do not tell residents to self-register when the official process is
club-mediated.

## C6. Required regressions

At minimum:

- November 2026 Mar Costa Dúos never produces championship days on 23-25 when
  FEPyC says 26-29;
- rich 17 October context survives Event projection;
- labelled schedule/duration facts render without distance/route collapse;
- details-source failure cannot corrupt/drop the base Pesca calendar;
- stale details cannot be promoted as current access truth later;
- no browser/OCR/AI;
- 05:10 remains one short-lived sequential preparation lifecycle.

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
  FEPyC fishing authority, Pesca details and CONVEGA;
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
- represent the correction as an **event-level** notice, not by attaching it
  to an arbitrary access option;
- minimally allow `AccessNotice.option_id` (or an equivalent in-memory field)
  to be absent for event-level notices; do not create a second notice hierarchy
  or persist new state merely for this;
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

Add optional presentation-only `image_url` to the **end** of
`EventAccessRecord` so positional construction remains backward-compatible.

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

## F5. Material time/place correction gate

A detailed long-lived root may also contain event time and place. Current v2
state does not retain those facts, so it cannot detect a later correction or a
reversion.

Do **not** bump event-access state speculatively in Slice F.

Before enabling any rooted sports source whose authoritative contract allows
time/place to change:

1. classify which root facts are genuinely mutable and source-observable;
2. if current v2 date correction is sufficient, keep state v2;
3. if time/place changes must be detected, write a narrow ADR refinement and
   introduce the smallest explicit semantic comparison state needed (likely a
   v3 migration or equivalent reviewed current-context keys);
4. preserve the existing root ID/options/triggers exactly through migration;
5. require `uncertain == null` before migration;
6. create a private v2 backup and define the same pre-first-publication rollback
   boundary used by ADR 0092;
7. emit one compact correction reply from current accepted presentation facts;
8. never edit the old root or create a second lifecycle.

A source is **not eligible for rooted rollout** while a known mutable root fact
would be left silently stale.

This closes the root-consistency gap without forcing a schema change before a
real source proves it is needed.

## F6. Tests

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

# Slice G — FPCV event-access projection + second access source + access-time correction

## Goal

Reuse the already-normalized FPCV details from Slice C to prove the
multi-source event-access path. **No PDF parsing or second FPCV source read
belongs in the access runner.**

## G1. One normalized observation -> EventAccessRecord

Project the same accepted `pesca_cv_details.json` facts into
`EventAccessRecord`.

For the reviewed 17 October case preserve:

- stable source-owned record identity that does **not** include mutable
  date/time/place/action URL;
- access kind = registration;
- event dates from the corrected occurrence;
- club-mediated audience/action wording;
- exact deadline;
- current source-backed action/contact;
- place/context needed for the complete root;
- optional event-specific image only if the official source later supplies one
  under a reviewed image contract.

The normal Event projection and EventAccessRecord must share the same source
fact identity; do not re-parse or re-translate the source.

## G2. Source-specific access freshness

Define FPCV details freshness from the measured source contract.

Do not copy CONVEGA's <=90-minute rule automatically.

At minimum:

- future timestamps fail closed;
- too-old details do not produce a current open/closing/cancelled claim;
- a failed current details refresh preserves last-good storage but cannot be
  promoted past the accepted freshness horizon.

## G3. Multi-source access orchestration

Current runtime is CONVEGA-only.

With FPCV as the second source, introduce only a small explicit source-batch
orchestrator:

- CONVEGA loader + its freshness;
- FPCV details/access loader + its freshness;
- deterministic record ordering;
- existing single global uncertain outbound slot;
- no plugin registry;
- no dynamic source discovery;
- no generic ownership resolver.

Existing event-access state remains v2 and can retain records from both sources;
`source` is already a non-empty immutable string rather than a hard-coded
CONVEGA enum.

## G4. Move the two event-access checkpoints earlier

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

## G5. Tests

- club-mediated wording does not imply direct public self-registration;
- closing-tomorrow and closing-today before exact deadline;
- no closing-today after deadline;
- FPCV details/source failure cannot promote stale access truth;
- no PDF/source read occurs inside the access runner;
- CONVEGA behavior remains unchanged;
- one ambiguous source-record publication blocks later record sends exactly as
  current v2;
- deterministic ownership prevents duplicate roots for one joined event.

# Slice H — FVBCV volleyball source

## Gate

A 2026-10-05 web recheck still shows server-rendered FVBCV competition/jornada
tables with explicit competition hierarchy and Guardamar team rows. That
supports the adapter direction but is not a production contract by itself.

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
- prefer one central fixture/jornada read or another small explicitly bounded
  request set; reject an N-per-team/N-per-category crawl;
- existing pre-morning refresh;
- exact local team aliases preserving A/B/category identity;
- `sport="football"` or `futsal` according to source;
- no scores/standings;
- source-backed competition context.

---

# Slice J — Turismo mass participation sport + delegated registration

## Gate

The 2026-10-05 official Turismo page for Media Maratón remains under an
`Actividades deportivas` surface and exposes event-specific race facts. This
is strong evidence for source-backed sports classification, but implementation
still begins with a production probe of the reusable discovery contract.

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

Automated provider facts still require a bounded browserless contract. If the
delegated provider cannot be read safely without JavaScript/browser
automation, keep the official event/action link and omit unsupported live
price/status facts rather than adding a browser.

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
5. when a Telegram lifecycle root is possible, stable root identity must not
   depend on mutable date/time/place/action/display-title facts;
6. date/time;
7. venue/locality;
8. competition context;
9. cancellation/postponement behavior where applicable;
10. access ownership when registration/tickets exist;
11. no new per-sport daemon/cron/database.

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

Every new source probe must also measure expected retained cardinality against
existing structural bounds (64 event-access records, 16 options per access
record, 128 triggers per record) and presentation bounds (EventAccessRecord
details <= 8). Raise no bound without an explicit reviewed reason.

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

## Cross-surface scenario tests

In addition to module-focused tests, maintain a small deterministic scenario
suite using local fixtures only. It must exercise the product as a lifecycle,
not just individual functions.

Required scenarios:

1. **Mass participation event**
   - current access opens -> one detailed root;
   - photo success/fallback behavior;
   - closing-tomorrow;
   - closing-today before deadline;
   - appears in Tomorrow/Weekend planning;
   - appears again in Sports Today;
   - absent from Morning;
   - planning/current-day posts remain standalone, not replies to the access
     root.

2. **Ordinary home team match without advance access**
   - no event-access record/root;
   - source-backed league/group/round context;
   - appears in planning and Sports Today only;
   - away/unknown-venue match is not accepted as Guardamar-local.

3. **Late cancellation/postponement**
   - Friday Weekend contains the verified Sunday fixture;
   - current-day fresh source exposes cancellation/move;
   - Sports Today publishes the explicit correction rather than silently
     omitting or calling it upcoming.

4. **Fishing source authority**
   - FPCV operational rows include 23-29 November;
   - FEPyC authoritative championship occurrence is 26-29;
   - no sports surface emits 23-25 as championship days.

5. **Ambiguous Telegram delivery**
   - primary send may have succeeded;
   - recovery cannot duplicate Weekend/Sports Today/Event Access.

6. **Mixed municipal programme**
   - sport and non-sport children share a programme;
   - general and sports sections do not duplicate the programme parent or lose
     either child.

These scenarios must run without web access, Telegram access or AI.

Before each production deployment:

1. re-fetch current `origin/main` and confirm the reviewed target commit is
   still based on the expected main;
2. compare any main changes since plan/PR review for event/runtime impact;
3. confirm no affected one-shot process is currently active;
4. `python -m compileall` on changed modules;
5. focused suite;
6. full suite;
7. production preview/read-only probe where source/runtime-specific behavior is
   involved;
8. record relevant state/crontab checksums before mutation;
9. no Telegram/state mutation during preview.

---

# Deployment sequencing

## Deployment 1 — delivery foundation

Slice A only.

No sports behavior change.

Observe one real Weekend lifecycle before relying on it for richer sports.

## Deployment 2 — sport model/source correctness + rich fishing facts

Slices B + C.

No Morning removal yet.

This deployment may add FEPyC/FPCV source-preparation files and enrich Event
presentation, but it does not yet publish a new Sports Today lifecycle.

Run source probes plus Tomorrow/Weekend previews and verify sport identity,
national-date authority, rich fishing context and dedup before Slice E.

## Deployment 3 — sports resident product

Slices D + E.

Use a safe local deployment window **after that day's 07:30 Morning Digest has
completed**. This avoids a partial rollout where Morning starts excluding sport
before the new Sports Today schedule is installed.

Operational order:

1. confirm no relevant one-shot event/Weekend/Tomorrow process is active;
2. record production SHA, current crontab and relevant state checksums;
3. deploy reviewed code;
4. run Sports Today/Tomorrow/Weekend previews with no Telegram/state mutation;
5. install the managed cron update containing Sports Today primary/recovery;
6. read back the entire managed block and verify unrelated jobs are unchanged;
7. verify Sports Today state path/permissions;
8. if cron installation cannot be completed, roll back the code **before the
   next 07:30** so Morning does not enter the sport-exclusion path without the
   replacement publication;
9. allow evening planning to use sports sections only after previews pass.

Atomic product requirements:

- Sports Today command and state present;
- chosen cron primary/recovery installed and verified;
- Tomorrow/Weekend sports sections preview correctly;
- Morning sport exclusion becomes active only in this deployment;
- no source network added by Sports Today.

## Deployment 4 — generic Event Access completion

Slice F.

Do not add Pesca access until photo/date/wording behavior is fully tested.

## Deployment 5 — Pesca access projection and shared checkpoint move

Slice G.

The FPCV PDF/source contract was already production-probed and normalized in
Slice C. This deployment adds no second PDF parser/fetch path; it only enables
the EventAccessRecord projection/orchestration and moves the shared access
checkpoints.

Prefer installing the moved event-access cron **after the old day's 13:47
recovery has completed** (or before the first new early checkpoint, with the
old rows removed in the same managed-block replacement). Never leave old and
new access schedules active for the same local day.

Before enabling the new source:

1. refresh/probe FPCV access state read-only;
2. run event-access preview and record every root/reply that would be due;
3. verify total retained v2 record cardinality remains below structural bounds;
4. confirm event-access state has `uncertain=null`;
5. install/verify the new shared checkpoint rows;
6. let the next scheduled run publish through the normal crash-safe lifecycle.

Do not silently baseline an already-open high-value registration merely to avoid
a first root; the preview is the operator gate for the expected publication.

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

Source snapshots must remain backward-readable or be isolated from old
readers.

For FPCV access specifically, the plan now keeps the strict existing
`pesca_cv_events.json` untouched and writes access enrichment to a new source
file that old code ignores.

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

The final cron patch must also update installer tests so they prove:

- managed-block replacement removes obsolete old access rows;
- exactly two Sports Today rows exist;
- exactly two shared event-access rows exist;
- no old+new access schedule survives together;
- installer remains idempotent;
- unrelated cron rows are preserved;
- service startup preflight behavior remains unchanged.

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
11. no enabled rooted sports source can leave a known mutable time/place fact
    silently stale; either its contract does not require tracking or the
    reviewed context-correction state is implemented;
12. explicit source-backed cancellation/postponement is surfaced in the
    appropriate current-day/root correction path;
13. the 12:47 deadline gap is removed by one shared earlier event-access window;
14. FPCV national dates cannot override authoritative FEPyC championship dates;
15. FPCV convocatoria access uses bounded approved text-PDF extraction only;
16. FVBCV/FFCV are enabled only after current live source contracts prove
    locality and status semantics;
17. no browser, new daemon, database, queue, generic sports framework or
    per-sport cron exists;
18. every source addition has focused tests, full-suite pass and documented
    source/runtime contract;
19. production deploy and rollback procedures are documented and tested.



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


---

## Plan review cycle 2 — state/backward compatibility

### Findings

1. **Extending `pesca_cv_events.json` in place was rollback-unsafe.**
   Current validation requires an exact event-key set; old code would reject a
   new snapshot carrying access fields.
2. A separate bounded `pesca_cv_access.json` written by the same 05:10 source
   process is the smallest rollback-safe correction. It adds no cron/daemon and
   cleanly separates calendar last-good from convocatoria/access last-good.
3. **Event-date correction is event-level.** Current `AccessNotice` requires
   an `option_id`; forcing a date correction onto the first/default option
   would be semantically wrong for multi-option events. The plan now allows a
   minimal optional option ID for in-memory event-level notices.
4. `EventAccessRecord.image_url` must be appended, not inserted, to preserve
   positional-call compatibility.
5. Existing event-access state v2 is rollback-compatible with additional Pesca
   records: its validator requires only a non-empty immutable `source`, not a
   hard-coded CONVEGA allowlist. The old runner will leave unrelated valid
   records in the same v2 map and only process its CONVEGA projection.

### Corrections made

- Replaced in-place Pesca snapshot expansion with a separate bounded access
  source snapshot under the existing 05:10 process.
- Added explicit event-level notice representation to Slice F.
- Tightened positional compatibility for EventAccessRecord.

### Result

No remaining persistent-state schema blocker found in this review. Slices A-G
can preserve rollback at the file/schema level.


---

## Plan review cycle 3 — source contracts / root consistency

### Current-source recheck

A fresh 2026-10-05 web review still supports the research assumptions:

- FEPyC exposes `26MC26` with exact 26-29 November 2026 Guardamar dates,
  national type and Dúos category;
- FVBCV exposes server-rendered current competition/jornada tables and explicit
  senior competition hierarchy;
- Turismo's Media Maratón page remains an official sports-category surface with
  start, distances, time limits and event-specific context.

These findings strengthen, but do not replace, Termux production probes.

### Findings

1. **Canonical access-root consistency extended beyond date.** A root may
   include time/place, while v2 state cannot detect their change. The plan now
   has a mandatory per-source gate rather than falsely declaring the problem
   solved by date correction alone.
2. A speculative state-v3 migration would be overengineering. The plan delays
   it until an enabled rooted source proves mutable time/place semantics, then
   requires the minimal reviewed comparison state before source activation.
3. Moving Sports Today after the 10:10-10:40 late event refresh would harm
   early events (the official 2026 Media Maratón started at 09:30). The plan
   therefore keeps Sports Today in the morning after pre-morning snapshots;
   no late sports polling is added generically.
4. Future mutable league adapters may be added to an existing bounded shared
   event-refresh opportunity only if their measured contract justifies it;
   that is a source-specific optimization, not a prerequisite or new cron.

### Result

No unresolved source-authority contradiction remains in the plan. Root
time/place corrections are now an explicit enablement gate instead of an
untracked risk.


---

## Plan review cycle 4 — operational sequencing / limits / cron

### Findings

1. **Deployment 3 was not operationally atomic.** Code and cron are separate
   mutations. Deploying before 07:30 could let Morning exclude sport while a
   failed cron install leaves no Sports Today replacement.
2. **Access schedule migration could double-run one day** if old 12:47/13:47
   rows survive while new early rows are added. The plan now requires one
   managed-block replacement in a safe window.
3. New access sources must be checked against existing structural bounds before
   enablement; the plan previously relied on tests but did not make cardinality
   an explicit production gate.
4. Main can move between planning and implementation. Every deploy now starts
   with a fresh ancestor/delta review rather than assuming this plan's
   `d6380775...` base is still current.
5. New/old Weekend implementations could race during deploy if an existing
   process is active. Process absence is now a preflight requirement.

### Corrections made

- Defined a post-07:30 deployment window and rollback deadline for the Sports
  Today/Morning handoff.
- Defined a no-double-schedule window for event-access cron migration.
- Added cardinality/presentation bounds to source gates.
- Strengthened cron installer assertions and current-main/process preflight.

### Result

No remaining operational-order or cron-migration blocker found in this review.


---

## Plan review cycle 5 — integration tests / overengineering / source cost

### Findings

1. Module-level tests alone could all pass while the same event behaves
   incorrectly across Event Access, Tomorrow, Morning and Sports Today.
   Cross-surface lifecycle scenarios are now mandatory.
2. Optional FPCV PDF/access failure must not poison the base fishing calendar.
   The plan now treats the access snapshot as an independently validated
   last-good output of the same 05:10 process.
3. Future federation adapters must not turn a visually simple competition page
   into N-per-team/category crawling. Central/bounded fixture access is now an
   explicit source gate.
4. Delegated registration providers remain browserless-only for automated
   facts. A JavaScript-only provider does not justify Playwright; the bot may
   retain the official delegated link while omitting unverified live state.
5. The review found no justification for a new Competition model, sports DB,
   generic provider registry, message queue, pagination protocol or per-sport
   schedule. All proposed abstractions still correspond to at least two real
   existing uses.

### Result

No remaining integration-test or obvious overengineering objection found in
this review.


---

## Plan review cycle 6 — document consistency / presentation dependency

### Findings

1. The plan was internally consistent after prior edits: no stale fixed cron
   minutes, no in-place Pesca schema expansion and no old Weekend collector
   assumption remained.
2. A deeper ordering issue remained: first sports activation in Slice E would
   have occurred **before** FPCV convocatoria enrichment in the old Slice G,
   producing correct but editorially inadequate fishing copy. That contradicts
   the agreed human-description contract.
3. Parsing the same official PDF later only for Event Access would also split
   one source observation into two parsing lifecycles.

### Corrections made

- Moved FPCV convocatoria/details probe, PDF permission, normalized details
  snapshot and Event presentation enrichment into Slice C, before any sports
  publication is activated.
- Renamed the new rollback-safe source file concept to
  `pesca_cv_details.json` because it serves both presentation and access.
- Slice G now only projects the already accepted details into Event Access,
  adds the second explicit access source and fixes the shared access schedule.
- Updated deployment sequencing accordingly.

### Result

The same FPCV document is now collected/normalized once and reused twice, and
the first resident sports release already meets the descriptive-quality
requirement. No new consistency objection remains after this correction.


---

## Plan review cycle 7 — identity stability / source-join boundary

### Findings

1. **Root identity must survive correction.** If a source-derived
   `record_id` contains mutable date/time/place/action data, a reschedule would
   create a second event/root and make the planned correction logic useless.
2. FEPyC should not become a parallel generic fishing Event merely to override
   FPCV dates. That would push an authority decision back into fuzzy global
   merge. It is cleaner and safer as a source-specific authority input to the
   fishing projection.
3. The shared planning loader must pass/read the new FEPyC authority and Pesca
   details paths explicitly so all planning surfaces use the same corrected
   fishing projection.

### Corrections made

- Added a global stable-root-identity invariant and onboarding gate.
- Required FPCV access IDs to exclude mutable schedule/presentation facts.
- Clarified FEPyC as a fishing authority snapshot consumed before generic Event
  merge.
- Added FEPyC/Pesca-details paths to the explicit local planning read contract.

### Result

No remaining source-identity or correction-thread break was found after these
changes.


---

## Plan review cycle 8 — final red-team audit

### Checks

- current `main` re-read at `d63807751fab0c08656748714ec1ab78d3739765`;
- planning branch merge-base is exactly that current main;
- branch diff contains only:
  - stabilized architecture research;
  - this implementation plan;
- no production Python, shell, cron, ADR, KB or state file has been changed;
- slice dependency graph is acyclic;
- FEPyC/FPCV correctness and rich facts precede sports publication;
- Weekend crash-safety precedes Weekend sports content;
- Sports Today and Morning exclusion share one controlled deployment boundary;
- Event Access generic completion precedes FPCV access rollout;
- mutable root identity survives date/time/place/action changes;
- source snapshot additions remain rollback-safe;
- exact cron minutes remain a production-preflight decision rather than an
  architectural assumption;
- new source adapters remain individually gated and cannot force a generic
  framework/browser/per-sport scheduler;
- cross-surface scenario tests cover the resident lifecycle rather than only
  isolated modules;
- all discovered research gaps are represented either as a concrete required
  work item or an explicit source-enablement gate.

### Findings

No new architecture, sequencing, state, source, delivery, runtime-cost,
rollback or test-coverage objection was found.

### Final judgment

The plan is now internally consistent, ordered by real dependencies and
sufficiently conservative for the current Termux architecture.

Architecture fixation completed with ADR 0100 before runtime implementation.
The next phase is:

1. implement Slice A;
2. review/test/deploy Slice A;
3. proceed slice-by-slice only after each preceding gate passes.

The Slice C runtime/PDF refinement remains intentionally deferred until Slice C
starts.

If `main` or an official source contract changes before a slice starts, run a
targeted delta review for that slice rather than reopening the entire plan.


## Implementation checkpoint — architecture fixation

On 2026-10-05 the accepted target architecture was recorded in
`adr/0100-dedicated-sports-event-presentation.md` and summarized in the KB and
decision log.

This checkpoint changes documentation only. Slice A begins only after the
architecture-fixation review confirms no runtime/source/state file changed and
no contradiction remains between ADR 0100 and this plan.


## Implementation checkpoint — Slice A

Slice A implementation is complete on the implementation branch and has passed
its iterative code-review/test cycle:

- shared dated-publication state extracted;
- Tomorrow state/schema preserved without migration;
- Weekend ambiguous-delivery duplicate risk closed with a separate crash-safe
  delivery state plus the legacy rollback marker;
- manual review found an old/new-runtime lock mismatch;
- that defect was fixed by holding both legacy and new Weekend locks;
- focused suite: 77 tests OK;
- full repository suite: 1608 tests OK;
- no cron/source/sports-content behavior changed.

The detailed gate record is
`research/2026-10-05-sports-slice-a-implementation-review.md`.

The final post-report run is green (77 focused / 1608 full tests). Slice A is
PASS. Slice B remains blocked only until the temporary branch-only verification
workflow is removed and the final branch diff/main-delta check confirms that no
untested application change was introduced.


## Implementation checkpoint — Slice B

Slice A is deployed and production-verified.

Slice B implementation is complete on the implementation branch:

- `Event.sport` appended without positional migration;
- FACV/Pesca preserve chess/fishing identity;
- merge protects conflicting known sports and preserves known sport through
  valid alias merges;
- deterministic presentation metadata added for currently accepted sport codes;
- no resident routing/source/cron/state behavior changed.

First verification cycle passed:

- focused suite: 64 tests OK;
- full repository suite: 1615 tests OK;
- manual code review found no additional defect.

Detailed gate:
`research/2026-10-05-sports-slice-b-implementation-review.md`.

The final branch-head run is green (64 focused / 1615 full tests). Slice B
implementation gate is PASS. Slice C remains blocked until temporary workflow
cleanup, merge and production verification of Slice B.


## Implementation checkpoint — Slice C source-contract gate

The Termux production source probe for Slice C is PASS on
`0c01686545ee90236a2ab33a433b6f24a17d789f`.

Measured contracts:

- FEPyC authority page: 33,826 bytes / 0.326 s;
- FPCV convocatoria index: 161,072 bytes / 2.465 s;
- exact FPCV PDF: 609,280 bytes / 1.474 s;
- `pdftotext -layout`: 8,442 bytes / 0.088 s.

Production source state and working tree remained unchanged. ADR 0101 now
authorizes only this bounded source/PDF class. Runtime implementation remains
blocked until the documentation-only ADR/KB consistency review is PASS.


## Implementation checkpoint — Slice C

Slice B is production-verified.

Slice C implementation now provides the source-correctness and rich fishing
facts required before sports publication activation:

- FEPyC `26MC26` is the exact national occurrence authority for the reviewed
  Mar-costa Dúos conflict;
- FPCV convocatoria details are normalized once in the existing 05:10 fishing
  lifecycle;
- the strict existing fishing calendar state remains rollback-compatible;
- authority/details use separate bounded state files;
- relevant PDF bytes are content-hashed daily and `pdftotext` runs only when
  row/content identity changed;
- source enrichment is projection-eligible for 36 hours;
- FPCV details are capped at four and no new cron/source lifecycle exists;
- the national Event preserves Campeonato de España / Dúos context;
- the provincial reviewed Event preserves qualification, schedule, duration and
  venue context.

The implementation went through repeated fix/test/review cycles; detailed
findings are recorded in
`research/2026-10-05-sports-slice-c-implementation-review.md`.

The latest application-head verification before the final review update passed
80 focused and 1639 full-suite tests. Additional regression coverage confirms
that changed index/PDF content fails closed instead of serving mismatched
last-good details, while an unchanged document may survive a transient fetch
failure within the 36-hour freshness window.

The final branch-head run is green (80 focused / 1639 full tests). Slice C
implementation gate is PASS. Slice D remains blocked until temporary workflow
cleanup, merge and production verification of Slice C.


## Implementation checkpoint — Slice C final red-team cycle

After an initially green implementation, manual review found and fixed two
additional fail-closed gaps:

- a known-changed FPCV document could temporarily retain superseded details if
  replacement parsing failed;
- declared two-by-three-hour heats were not cross-checked against programme
  intervals.

The corrected runtime now preserves last-good only for an unavailable fetch of
the same document, withholds known-superseded invalid details immediately, and
validates the heat schedule against the declared duration.

Post-fix verification:

- focused Slice C suite: 80 tests OK;
- full repository suite: 1639 tests OK.

Slice C remains blocked from merge/deploy until the final documentation
branch-head run and temporary-workflow cleanup are complete.


## Implementation checkpoint — Slice C gate

The final documentation branch head passed compileall, 80 focused tests and
1639 full-suite tests. Slice C implementation gate is **PASS**.

No new cron, resident-facing sports publication, Event Access source, browser,
OCR, runtime AI or dependency is introduced by Slice C. The temporary
verification workflow remains cleanup-only; Slice D stays blocked until Slice C
is merged and production-verified.
