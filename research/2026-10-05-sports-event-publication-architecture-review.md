# Sports event publication and event-access architecture review — 2026-10-05

## Status

In progress.

This review re-evaluates the sports-event product after the operator clarified that:

- sports should not be repeated inside the Morning Digest;
- next-day sports may be presented as a dedicated section inside the existing `Завтра в Гуардамаре` / Friday weekend planning surfaces instead of requiring another evening message;
- today's sports should receive a separate resident-facing morning/daytime post even when the event was already announced for tomorrow;
- long-lead registration/reservation/ticket changes should reuse the existing event-access lifecycle and one event root rather than invent a sports-specific notification engine;
- the first/root event card should preferably contain one event-specific official image and a complete human-readable Russian description;
- later access updates (deadline tomorrow/today, full, closed, reopened, etc.) should be strict replies to that event root;
- sports descriptions should explicitly say the sport, participants/teams, venue, useful context and official/approximate duration when source-backed, rather than exposing opaque club/provider names.

No production code, cron or Telegram behavior is changed by this research branch.

## Current architecture findings

### Event-access v2 is the correct reusable lifecycle

ADRs 0090-0092 already define:

- one source-owned event/access record;
- one Telegram root per event;
- strict threaded replies for later lifecycle changes;
- `registration`, `reservation` and `ticket` access kinds;
- opening-tomorrow/today, closing-tomorrow/today, deadline-known/changed, full/closed/reopened and option-added semantics;
- crash-safe uncertain delivery state.

Therefore sports registration/ticket handling must project source facts into this existing lifecycle. A sports-specific registration state machine would be overengineering.

### Photo root is approved but NOT implemented in event-access runtime yet

ADR 0090 explicitly accepts an event-specific official poster/image for the root and defines the required crash-safety/fallback policy.

However current `event_registration_notifications.py` imports and uses only `send_message()`. Normal event-access roots are text-only.

The Telegram layer already has `send_photo_url()`, and the existing `Tomorrow Events` delivery already implements:

- approved official image URL validation;
- photo only when the complete message fits Telegram's caption limit;
- uncertain reservation before send;
- retry only for explicit rate limits;
- deterministic remote-media rejection -> safe text fallback;
- ambiguous delivery -> no automatic fallback/resend.

The event-access photo-root work should therefore reuse this proven delivery pattern rather than introduce a new media subsystem.

### Tomorrow/Weekend are better next-day/weekend sports surfaces than another sports-evening cron

Current schedules:

- Friday `Афиша выходных` covers Saturday + Sunday at 19:15, recovery 20:15.
- `Завтра в Гуардамаре` runs Sunday-Thursday at 19:25, recovery 20:25.
- Friday/Saturday next-day runs are intentionally suppressed to avoid duplicating the weekend digest.

Therefore an additional daily evening `sports tomorrow` cron would duplicate an existing planning lifecycle and create avoidable schedule/message noise.

Preferred direction under review:

- add a clearly separated `🏅 Спорт` section to the existing next-day publication;
- add sports to the Saturday/Sunday day blocks of the Friday weekend digest;
- create only one new sports-specific current-day publication surface, e.g. `🏅 Спортивные мероприятия сегодня`.

The same sports event may intentionally be mentioned twice for different user decisions:

1. planning view before the day (tomorrow/weekend);
2. current-day reminder on the event date.

That is not accidental duplication if the copy and timing are intentionally different.

### Morning Digest should stop carrying sports once current-day sports publication is enabled

Today FACV/Pesca are ordinary `Event(category="event")` values and are consumed by Morning/Weekend/Tomorrow.

A separate current-day sports publication makes Morning sports repetition unnecessary. Removal must be deployed atomically with the new sports-today path so events cannot disappear between releases.

### Current normalized Event loses the sport identity

FACV source state contains `sport="chess"`; Pesca contains `sport="fishing"`.
Both adapters currently project those rows to `Event(category="event")`, losing that identity.

Keyword classification of Russian/Spanish titles would be fragile and must not become the production rule.

The smallest explicit model change under review is:

```python
sport: Optional[str] = None
```

on `Event`, propagated from source-owned facts and through cross-source merges.

Do not overload the existing `category` field: it already describes presentation/event type such as event/exhibition and has existing rendering semantics.

Municipal/Turismo sports need source-backed classification (structured category/provenance or an explicitly reviewed source projection), not title-keyword guessing.

## Product copy requirements under review

A sports item must be understandable without knowing Spanish club branding.

Bad:

- `Grupo Nexus Guardamar — CV Elche`
- `Guardamar Soccer`

Preferred structure:

- explicit sport label in Russian;
- human-readable competition/action;
- both teams/participants when applicable;
- avoid repeating Guardamar merely as city context;
- retain `Guardamar` only when it is genuinely part of a club/team proper name;
- official start/end or duration when source-backed;
- approximate duration only when there is a reviewed deterministic sport-specific rule and it is clearly marked approximate;
- venue;
- admission/registration facts only when explicitly supported.

No guessed free entry, duration, cancellation or availability.

## Publication lifecycle model under review

One event can legitimately have several surfaces without several semantic event records:

```text
source-owned event/access facts
        |
        +--> event-access root + lifecycle replies
        |
        +--> tomorrow/weekend planning projection
        |
        +--> sports-today reminder projection
```

These are presentation/delivery projections of the same source facts, not independent collectors.

Important open design question: planning/current-day aggregate posts should normally remain standalone editorial publications, not replies to an event-access root. A single planning post may contain several events and therefore cannot have one unambiguous event root. Where useful, the aggregate item may link back to the source/root later, but that must not create a second lifecycle identity.

## Source/freshness findings retained from prior research

- FACV and Federación Pesca CV are already implemented as bounded official sources and refresh inside the existing 05:10 wrapper; no new cron is justified for them.
- Pesca CV payload is already ~1 MiB, so it must not be re-fetched casually in each publication path.
- Mutable league fixtures (future FVBCV/FFCV adapters) may require a separate reviewed same-day/evening freshness contract, but that is source-specific.
- Static season PDFs must not be treated as authoritative live football fixture state when the federation exposes postponements/suspensions elsewhere.
- FEPyC vs Pesca national Mar-Costa Dúos date semantics need fact-level authority review; do not build a generic source-precedence framework.

## Known gaps still to review

1. exact current-day sports publication timing and recovery slot against every existing cron;
2. whether sports-today should use a new tiny at-most-once delivery state or can safely reuse/refactor the existing Tomorrow state without destabilizing it;
3. exact renderer sharing between Tomorrow/Weekend/Sports Today without turning `build_event_section()` into an over-generic formatter;
4. propagation of `sport` through `_merge_events()` and source projections;
5. source-backed identification of municipal/Turismo sports;
6. human-readable sport labels/team naming/duration semantics;
7. event-access access-kind wording (current renderer still contains registration-specific headings for some generic access kinds);
8. photo-root state/delivery fields needed for event-access without unnecessary media state;
9. whether the current event-access record needs an optional image URL as presentation-only data;
10. source-specific cancellation/postponement behavior for future league adapters;
11. tests and safe rollout order ensuring sports do not disappear from existing publications before new paths are live.

