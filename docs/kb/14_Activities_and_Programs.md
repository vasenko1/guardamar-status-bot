# Activities and Programs

Status: planning — 2026-09-16

This note is the working product/technical plan for the linked Guardamar guide. It records agreed scope and sequencing so the implementation does not depend on chat history.

## User-facing information architecture

Use two sibling guide branches under `Полезное о Гуардамаре`:

- `🎓 Занятия и секции` — recurring or season-long activities, clubs, schools and municipal programs.
- `🏕 Программы на каникулы` — short-lived programs tied to school holidays (summer, Semana Santa, Christmas, etc.). Keep this card durable even when no current program is published.

Do not call holiday programs simply `лагеря`: some are day programs without accommodation. `Программы на каникулы` is the preferred Russian label.

Do not expose the administrative Spanish label `Dinamización Social` as the primary user-facing title. Prefer `🤝 Муниципальные занятия и мастерские`; the detail card may mention the official program name as a secondary source label.

## Deployment sequence

### Deploy 1 — finish sports only

Keep this deployment limited to the existing linked-guide and Sporttia architecture.

Add:

- `Complejo Deportivo Les Raboses` as a durable place card.
- `CEIP Molivent` as a durable place card.
- `DEPORTE +` from the existing Sporttia centre read.
- `Психомоторика` from the existing Sporttia centre read (two current groups at CEIP Molivent).
- `Футбол` as a durable Guardamar Soccer C.D. activity card linked to Les Raboses; do not pretend it is Sporttia-managed.
- Venue links inside activity cards must point to the internal Telegram place card when one exists. The place card owns the `Открыть на карте` action. This must match the current Palau Sant Jaume pattern.
- Split activity-to-place membership explicitly: Palau activities, Les Raboses activities, and CEIP Molivent activities. Do not keep using one overloaded `SPORT_ACTIVITY_KEYS` set as an implicit venue model.
- Adapt recovery tests so deleting a place or a source-managed activity recreates and relinks only the correct graph edges.

Current Sporttia target after this deploy: cover all 15 currently published municipal rows from the one existing bounded centre-page GET.

Do not add in this deploy:

- a second Sporttia source,
- per-activity Sporttia requests,
- occupancy `Alumnos X/Y`,
- interpretation of generic Sporttia `Abierta/Cerrada`,
- music/social/holiday program source code.

### Deploy 2 — recurring non-sport activities

Add at least:

- `🎼 Школа музыки` / Jardín Musical and Escuela de Música.
- `🤝 Муниципальные занятия и мастерские` for the current `Dinamización Social` campaign.
- `📚 Школа для взрослых · EPA` when the current-year facts can be taken from an official source without carrying forward old schedules.
- Later annual programs such as `Dale Vida a los Años` when a new campaign is published.

Do not flatten every workshop into the `Занятия и секции` index. One program card may contain several groups/workshops.

### Deploy 3 — holiday programs

Add durable `🏕 Программы на каникулы` and monitor a small explicit allowlist of recurring Guardamar sources. Current candidates:

- Campus Juanma Ortiz — stable `campusjmortiz.com/inscripcion` page; recurring football camps at Les Raboses.
- Nautilus Nautical Sports — stable Guardamar camp page with spring/summer programs.
- GoSportmadness — Guardamar summer-school pages; discover through a narrow Guardamar/category surface rather than hard-coding a year-specific detail URL.
- Official Ayuntamiento/municipal publications — discovery source for municipal holiday programs.

Do not build a generic web crawler. Do not auto-publish Xpert or other ambiguous commercial pages until current year, Guardamar location, dates and registration state are unambiguous.

## Source-cost decisions

### Sporttia

Keep ADR 0069's one bounded daily centre-page GET. It already contains the published rows, season, explicit `NUEVAS INSCRIPCIONES`, schedule, venue and activity URLs.

Treat three concepts independently:

1. explicit registration windows from `NUEVAS INSCRIPCIONES`;
2. Sporttia's generic `Abierta/Cerrada` operational status;
3. occupancy/capacity such as `Alumnos X/Y` or `Plazas X/Y`.

Only (1) is part of the current production contract. `Abierta` is known not to mean free places and must not drive `есть места`, `мест нет`, or the card CTA. Occupancy remains a separate research item.

### Agrupación Musical Guardamar

The project already has an approved bounded WordPress REST adapter at `src/telegrambot/am_guardamar.py`: one request for twelve recently modified posts. It intentionally rejects titles containing `matrícula`, `curso`, `horarios`, `plazas`, etc. from the event pipeline.

For Deploy 2, prefer a small separate program extractor over changing event semantics. Reusing the same endpoint with one additional bounded daily GET is acceptable and safer than refactoring the existing event catalog solely to save one HTTP request. Consolidate only if measured runtime/network cost justifies it.

Track at least: Jardín Musical, Escuela de Música, enrollment windows, age, schedule facts explicitly published by the school, contact and registration URL.

### Ayuntamiento / Guardamar municipal site

The official site exposes a WordPress RSS feed (`/feed/`) and publishes campaigns such as `PROGRAMA DINAMIZACIÓN SOCIAL 2026 / 2027` in the normal news surface. Prefer one bounded feed/list request as discovery rather than crawling municipal pages.

On a new/changed matching campaign, fetch its detail once, normalize durable facts, and retain a last-good snapshot. If the registration form contains extra schedule/group detail, fetch it only when the campaign is new/changed; do not poll the form every day.

This source can later discover `Dinamización Social`, EPA notices, `Dale Vida a los Años`, and municipal holiday programs, but each campaign needs an explicit classifier/contract before public output.

### Holiday program sites

Use at most one small stable page per approved organizer, once daily while the feature is active. Store a compact normalized/fingerprinted snapshot. Fetch extra detail only after a visible change.

Engineering simplicity is more important than avoiding a handful of small daily GETs. Do not introduce a generic scheduler or shared-cache framework merely to save 2–4 requests/day.

## Sports notification contract

Public sports notifications may be sent for these material changes only:

- a genuinely new activity after the alert baseline has already been established;
- a new group/turno in an existing activity;
- start of an explicit `NUEVAS INSCRIPCIONES` window;
- changed/extended/shortened registration windows;
- one useful reminder shortly before an explicit registration deadline;
- changed schedule;
- changed venue;
- changed age/audience;
- changed season dates;
- changed explicit participation requirements (medical certificate, companion, independent participation, association membership, etc.);
- appearance/removal of explicit `hasta completar` / until-full wording;
- publication of a new season;
- newly published approved holiday program/campus in the holiday-program feature;
- explicit cancellation/suspension only when the source actually states it.

Do not notify for:

- raw HTML changes,
- row reordering,
- generic `Abierta/Cerrada`,
- occupancy until a separate contract exists,
- source failure,
- disappearance from the Sporttia centre open-registration surface alone.

First observation after a parser/source rollout is a silent alert baseline so deployment does not falsely announce old activities as newly created. Current time-sensitive registrations may instead receive one deliberate launch overview.

## Current urgent product facts (2026-09-16)

- Sporttia's current 2026/27 registration windows for the targeted municipal sports generally include September and end on 2026-09-30 where explicitly published.
- Jardín Musical (ages 3–6) has an exceptional enrollment extension through 2026-09-17 on the official Agrupación Musical Guardamar site. This is time-sensitive and should not wait for a future automatic change event if Deploy 2 is not ready in time.

## Open research, not blockers for Deploy 1

- Sporttia occupancy/status second layer: determine whether all relevant Guardamar capacity/status facts can be obtained by one bounded public request without auth, browser automation or per-activity crawling. Do not change ADR 0069 until that contract is proven.
- Before implementing the municipal-program adapter, make one production-network probe of the Ayuntamiento RSS/list response: final URL, content type, size and encoding.
- Before implementing each holiday source, confirm final URL, redirect policy, response size and the minimum deterministic fields required to distinguish an active current-year Guardamar program from stale history.

## Anti-overengineering rules

- Extend existing guide/state/recovery patterns; no generic CMS.
- Prefer explicit source-specific classifiers over an abstract plugin framework.
- One extra bounded GET/day is acceptable when it keeps features isolated.
- No browser automation for ordinary public program discovery.
- No new daemon/cron when an existing daily guide/catalog refresh can carry the work.
- Persist normalized facts and message IDs, not raw unbounded pages.
- Update this note as each deploy is completed or a source contract changes.
