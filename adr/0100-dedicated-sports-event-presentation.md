# ADR 0100: Dedicated sports event presentation on the shared event pipeline

- Status: Accepted
- Date: 2026-10-05
- Implementation: Pending; staged by the reviewed sports implementation plan
- Research: `research/2026-10-05-sports-event-publication-architecture-review.md`
- Plan: `research/2026-10-05-sports-event-implementation-plan.md`
- Refines: ADR 0080, ADR 0090, ADR 0091, ADR 0092

## Context

The bot already collects future and same-day local events from municipal,
association and federation sources and projects them into one additive `Event`
model used by Morning, Tomorrow and Weekend.

Sports create three distinct resident decisions that should not be conflated:

1. secure access well before the event when registration, reservation or ticket
   action is required;
2. plan tomorrow/weekend activities;
3. decide what can be attended today.

Putting the same sport row into every generic surface creates noise, while a
second sports collection stack would duplicate source work, identity,
deduplication, state and scheduling.

Current federation snapshots also already know explicit sport identity
(`chess`, `fishing`) but lose it when projecting into the global
`Event(category="event")` model.

The accepted event-access architecture in ADRs 0090-0092 already owns the
long-lead access lifecycle: one source-owned event root, strict threaded
replies, source-proven options and crash-safe uncertain delivery. Sports must
reuse that lifecycle rather than create a second registration system.

## Decision

### One shared event fact pipeline

Sports remain normal events.

Add one optional normalized field to the global Event model:

```python
sport: Optional[str] = None
```

This field means both "this event is sport" and "which sport is it". It does
not replace `category`, which retains existing event/exhibition presentation
semantics.

Do not introduce a SportsEvent database/model, provider registry, generic
sports crawler, per-sport state machine or per-sport scheduler.

Existing and future source adapters own the canonical sport code. Global
keyword classification of translated/source titles is not an authoritative
classification path.

### Merge semantics

Sport identity participates in deduplication:

- known sport + no sport may merge under the existing identity evidence and
  preserves the known sport;
- the same known sport may continue through existing merge rules;
- two different known sports may not fuzzy-merge as one event.

Source-owned fixture/competition IDs remain in source snapshots; they do not
become speculative global Event fields.

### Resident presentation surfaces

Sports use the existing planning lifecycle plus one current-day surface.

#### Tomorrow / Weekend

- `Завтра в Гуардамаре` gains a clearly separated sports subsection.
- Friday `Афиша выходных` gains the same sports subsection inside each
  relevant day.
- No separate evening `Спорт завтра` message or cron is added.
- Friday/Saturday Tomorrow suppression remains controlled by ADR 0080.

#### Sports Today

Add one standalone, local-snapshot-only publication for the current local day,
conceptually:

`🏅 Спортивные мероприятия сегодня — <date>`

It performs no source HTTP and no AI. It sends nothing when no current,
source-proven sporting event or explicit same-day correction is useful.

Once this current-day sports surface is deployed and verified, the Morning
Digest excludes `Event.sport != None` so sport is not repeated inside the
07:30 briefing.

The planning mention and current-day mention are intentional separate resident
decisions and are not deduplicated against one another.

### Sports copy is resident-facing, not a raw federation row

A published sport block should preserve the source-backed useful context when
available:

- sport in Russian;
- participants/teams;
- competition/division;
- group;
- numbered round/jornada or explicit knockout/qualifying/friendly stage;
- material team/category distinction;
- schedule;
- venue;
- format/distance;
- official time limit or source-known duration;
- current access fact when safely joined.

Do not infer a final, semi-final, qualifier, friendly, free entry, duration or
importance from calendar position or missing data.

Competition context is presentation data and initially remains in ordered
`Event.details`; no global Competition object is introduced.

Multiple race distances must use labelled detail lines rather than bare
parallel distance strings because the generic route-distance renderer may
otherwise normalize them as alternative route measurements.

### Locality

A Guardamar team playing away is not a Guardamar city event.

A federation fixture becomes publishable only when the accepted source contract
can prove that the occurrence physically takes place in Guardamar. "Local club
is home" is not sufficient on its own because venues can move.

### Multi-day sport

A date range does not imply daily competition.

Each sports source contract must prove whether every day in a normalized range
is an active competition day. Otherwise the existing first/final-day planning
semantics remain.

### Event-access reuse

Registration, reservation and ticket lifecycles remain owned by ADRs 0090-0092.

Sports adapters may additionally project source-owned
`EventAccessRecord` values, but:

- no sports-specific access state machine is allowed;
- stable root identity must not depend on mutable date, time, place, action URL
  or display title;
- later access changes remain replies to the stored event root;
- planning/current-day aggregate posts remain standalone and never become
  replies to one event's access root.

The generic event-access implementation must be completed before sports access
sources depend on it:

- access-kind-correct wording;
- material event-date correction replies;
- ADR 0090 photo roots using the existing crash-safe Telegram media policy.

If an enabled rooted source can materially change a root fact such as time or
place, the source may not launch until that correction can be detected and
reported through a reviewed minimal lifecycle refinement.

### Photo policy

The long-lived event-access root is the preferred place for one exact,
event-specific official poster/image.

Later lifecycle replies stay text-only and do not repeat the poster.

Planning posts retain ADR 0080 media behavior: one eligible editorial unit may
use one approved official image; multi-event planning remains text.

Do not use a venue photo, generic monthly poster or team logo merely to force
media.

### Current-day correction

When a responsible source explicitly marks a previously planned occurrence
cancelled or postponed, Sports Today must surface that correction rather than
silently omit the event.

A rooted event uses the same event-access root for a material source-backed
correction. Ordinary fixtures without an access root remain planning/current-day
events; no generic cancellation daemon is created.

### Source authority remains fact-specific

Do not create a global source-priority engine.

For the reviewed fishing conflict:

- FEPyC owns exact national championship occurrence dates;
- FPCV owns explicit regional/local organizational and access facts.

Authority is joined source-specifically before the generic Event merge.

### Rendering completeness

A sports aggregate must not silently lose tail events because a renderer budget
was reached.

Sports planning/current-day rendering must preserve every eligible event's
identity, sport, competition context, time and place. Optional prose may be
removed first. If the complete bounded aggregate still cannot fit Telegram,
fail closed and measure real volume before introducing pagination or a
multi-message transaction protocol.

### Runtime constraints

The first sports publication slice reuses accepted local snapshots and existing
source refreshes.

Do not add:

- browser automation;
- runtime AI;
- database/queue;
- daemon/worker;
- per-sport cron;
- unbounded source requests.

New federation/organizer adapters are admitted one at a time only after a
bounded browserless production source contract is proven.

## Implementation sequence

The accepted sequence is intentionally staged:

1. crash-safe dated planning delivery, including the existing Weekend ambiguity
   gap;
2. `Event.sport` and sport-aware merge/presentation;
3. FEPyC/FPCV fishing authority and rich normalized details before sports are
   publicly activated;
4. shared complete local planning render path;
5. Tomorrow/Weekend sports sections + Sports Today + Morning sport exclusion;
6. generic event-access completion;
7. FPCV access projection and earlier shared event-access checkpoint window;
8. FVBCV, FFCV, Turismo/mass participation and later sources one at a time.

Every stage has a verification gate. A later stage must not begin until the
current stage passes its focused tests, full suite, architecture/code review and
any required production-safe probe. A found defect restarts the
fix -> test -> review cycle for that stage.

## Consequences

### Benefits

- one factual event model and one source pipeline;
- sports receive useful dedicated presentation without an extra evening message;
- Morning becomes less repetitive;
- access lifecycle reuses the already deployed event-centric state;
- source-specific competition context stays factual;
- Termux network/process cost remains bounded;
- later sports can be added adapter-by-adapter.

### Costs

- one new Event field and a current-day sports publication path;
- planning rendering/delivery must be hardened before sports activation;
- federation adapters must preserve richer occurrence identity/context;
- source-specific cancellation/locality contracts need explicit review;
- the FPCV/FEPyC conflict must be corrected before fishing is used by the
  sports surfaces.

## Alternatives rejected

### Separate sports database / event model

Rejected. It duplicates event identity, collection, merge and rendering.

### Separate daily "sport tomorrow" publication

Rejected. Existing Tomorrow/Weekend already own planning before the day.

### Keep sports only in Morning

Rejected. It is too late for some planning use cases and makes Morning denser;
a dedicated current-day message is clearer.

### Publish Tomorrow but not Sports Today

Rejected. The same-day reminder/correction is independently useful and can
reflect the newest accepted morning source state.

### Global keyword sport classifier

Rejected. It can misclassify routes, festivals and ambiguous tournaments.

### Generic competition schema now

Rejected. Current source-backed league/stage/race context fits ordered Event
details; add structure only when implemented sources need program logic on
those components.

### Generic source-precedence / ownership engine

Rejected. The current overlaps are few and have deterministic source-specific
authority/ownership rules.
