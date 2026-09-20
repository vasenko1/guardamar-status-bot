# Activities and Programs

Status: implementation ledger — Deploy 3 completed 2026-09-17

This note is the living product/technical plan for the linked Guardamar guide. It records agreed scope, source contracts, information architecture, implementation gaps and deployment order so future work does not depend on chat history.

It is intentionally not an ADR. ADRs record accepted architectural decisions after a source/implementation contract is proven; this file tracks planned work and is updated as each slice is implemented, deferred or rejected.

## Documentation roles

- This file (`14_Activities_and_Programs.md`) is the single living implementation ledger for activities/programs.
- `09_Roadmap.md` remains high level; do not duplicate item-by-item implementation detail there.
- `06_Data_Sources.md` is updated only when a source role is actually approved/implemented.
- `11_Pinned_Message_Content.md` records final resident-facing guide copy/rules and is now synchronized with the current root/places/activities architecture.
- ADR 0067 remains the base linked places/activities architecture. ADR 0069 remains the current Sporttia source contract. New accepted source/notification contracts should receive narrow ADRs only when implemented.

## Resident-facing information architecture

Use two sibling guide branches under `Полезное о Гуардамаре`:

- `🎓 Занятия и секции` — recurring or season-long activities, clubs, schools and municipal programs.
- `🏕 Программы на каникулы` — short-lived programs tied to school holidays (summer, Semana Santa, Christmas, etc.). Keep this card durable after the feature exists, even when no current program is published.

Do not call holiday programs simply `лагеря`: some are day programs without accommodation. `Программы на каникулы` is the preferred Russian label.

Do not expose the administrative Spanish label `Dinamización Social` as the primary user-facing title. Prefer `🤝 Муниципальные занятия и мастерские`; the detail card may mention the official program name as a secondary source label.

### Root depth

Do not create an additional `Досуг`, `Образование`, `Спорт` or similar navigator above/below the current root yet. The root can remain one compact navigator with cameras, transport, places, Wi-Fi, recurring activities and holiday programs.

`Занятия и секции` should remain one index message. As it grows, group rows visually inside the same message instead of adding another navigation level:

```text
🎓 Занятия и секции

🏃 Спорт и движение
🏊 Плавание
🤸 Художественная гимнастика
🥋 Дзюдо
…

🎵 Музыка
🎶 Музыкальное развитие и грамота
🎤 Вокал и хор
🎷 Музыкальные инструменты

🤝 Другие программы
🧩 Муниципальные занятия и мастерские
📚 Школа для взрослых · EPA
```

This is presentation grouping only; it does not create category messages or category state. Introduce a new intermediate Telegram card only after real content proves that one index or one program card is too long/hard to scan, not pre-emptively.

### Card granularity

Use one durable card per resident-recognizable activity/program, not one card per source row or timetable group.

- Several Sporttia `turno` rows for the same activity stay inside one activity card.
- Music is activity-first: Jardín/Lenguaje Musical share `Музыкальное развитие и грамота`, while vocal and instruments have their own compact cards; the provider/place is linked separately.
- `Муниципальные занятия и мастерские` may contain several workshops/groups inside one program card.
- `Программы на каникулы` is an aggregate current-program card; do not create a permanent Telegram card for every historical camp.

If a real program card approaches Telegram’s practical message-size/readability limit, split only that program at the narrowest useful boundary. Do not add a generic hierarchy framework in advance.

### Place-card rule

Do not require every activity venue to have its own internal place card.

Create a durable place card when the place itself has independent resident-facing value, for example multiple linked activities/facilities, useful stable contacts/objects, or a durable role in the guide. When such a card exists, activity venue text links to the internal Telegram card and that card owns the `Открыть на карте` action.

For a one-off holiday program at a venue that has no other useful guide content, a direct map link from the program card is acceptable. This avoids turning `Места` into a directory of every school/building used once.

Current justified durable place cards in this scope:

- Polideportivo Municipal and its existing child facilities;
- Palau Sant Jaume;
- Complejo Deportivo Les Raboses;
- CEIP Molivent (current recurring municipal psychomotor activity plus durable school location);
- Centro Social Juvenil;
- Escuela de Música (shared place/contact card for several music activities).

Future places such as CEIP Reyes Católicos should receive cards only when their actual guide value justifies one, not merely because a source mentions the venue.

## Code architecture audit

The current architecture remains suitable after Deploy 1. Keep the existing one-shot Termux model, atomic JSON state, source-specific adapters and linked-message reconciliation.

### Resolved in Deploy 1 — source keys and venue membership are separate

The old `SPORT_ACTIVITY_KEYS` tuple represented too many responsibilities at once. Deploy 1 split those responsibilities explicitly without introducing a Place/Activity relation engine:

```python
SPORTTIA_ACTIVITY_KEYS = (... existing ..., "deporte_plus", "psychomotricity")
PALAU_ACTIVITY_KEYS = (... existing six ...)
LES_RABOSES_SOURCE_ACTIVITY_KEYS = ("deporte_plus",)
MOLIVENT_SOURCE_ACTIVITY_KEYS = ("psychomotricity",)
```

Football remains a durable static activity and is not part of Sporttia source keys.

### Resolved in Deploy 1 — venue rendering

`_venue_markup` now recognizes only the three supported durable sport venues explicitly: `Palau Sant Jaume`, `Complejo Deportivo Les Raboses`, and `CEIP Molivent`. The recognized place name links to its internal Telegram card when available; a verified map is the recovery fallback. Source sublocation text remains plain escaped text.

This remains a presentation lookup, not a generic place ontology. Unknown venues remain escaped plain text.

### Resolved in Deploy 1 — source-card rollout guard

`publish_pinned_guide` no longer manufactures a newly introduced source-managed card merely because a source key exists in code. A new source card is created only when current/future normalized groups are available. An already-created source card can still participate in normal recovery using last-good catalogue data.

No second Sporttia request, override fetch, scheduler or cron was added for same-day deployment timing.

### Resolved in Deploy 1 — venue-aware recovery

Recovery remains on the existing bounded reconciliation passes. Palau activities relink to Palau; DEPORTE+ relinks to Les Raboses; psychomotricity relinks to CEIP Molivent; static football relinks to Les Raboses. Deleting a place does not reassign unrelated activities to it.

No graph database, dependency engine or generic relation layer was introduced.

### Constraint — `guide.py` must stay an orchestrator

`guide.py` coordinates Aqualider, Sporttia, Wi-Fi, pinned reconciliation and the pool-season notice. Do not place future HTML/RSS/WordPress parsing into this module.

Follow the existing project pattern:

- source-specific access/normalization in small modules such as `sporttia.py`, `am_guardamar.py`, and future narrow modules for municipal/holiday programs;
- `guide.py` calls them sequentially, handles last-good state and then reconciles Telegram cards.

No plugin framework, provider registry, dependency injection container or generic source scheduler is needed.

### Constraint — the existing guide state can grow safely

Keep `state/guide.json` as the small atomic guide/source state. Add optional, independently validated top-level normalized snapshots as features land (for example music/municipal/holiday catalog state) instead of introducing a database or one file per activity.

Do not persist raw pages. Preserve last-good normalized facts on source failure. New optional keys must be backward-compatible with existing state.

Notification delivery state may be separate when it needs explicit `pending/uncertain` semantics; do not overload `pinned_guide.json`, whose job is message IDs/media graph state.

### Constraint — notification semantics should copy the proven pattern, not its module

`transport_notifications.py` already proves the useful delivery ideas: silent first baseline, semantic diffs, batching, atomic pending state, and `uncertain` before `sendMessage` because Telegram has no idempotency key.

Sports/program notifications should use those same small invariants but should not import or generalize transport notification internals into a universal notification framework.

## Termux/runtime budget

The daily `sync-guide` one-shot now runs at 09:02 Europe/Madrid so explicit
same-day registration boundaries can be observed before resident
notifications. It remains one short process, writes a bounded rotating log and
exits. Source request counts did not increase; only the time of day changed.

`course_notifications` runs at 09:42 with an 11:42 same-day retry slot. It
performs zero source-network requests and reads only accepted local
`guide.json` / `pinned_guide.json` state. The second invocation is normally
an immediate no-op.

Accept a handful of small sequential bounded GETs per day. On this project,
engineering isolation is more valuable than saving 1–4 HTTP requests/day. Do
not add a daemon, resident watcher, thread pool, browser automation, database,
message broker or generic notification framework.

## Deployment sequence

### Deploy 1 — sports core / linked guide only — completed 2026-09-17

Implemented as one extension of the existing linked-guide and Sporttia architecture:

- durable `Complejo Deportivo Les Raboses` place card;
- durable `CEIP Molivent` place card;
- source-managed `DEPORTE +` from the existing Sporttia centre read;
- source-managed `Психомоторика` with two current CEIP Molivent groups and the source’s overlapping 2022 audience year preserved;
- durable static `Футбол` card for Guardamar Soccer C.D., linked to Les Raboses and deliberately not treated as Sporttia-managed;
- internal venue links matching the existing Palau UX, with verified map fallback during recovery;
- explicit source/venue key separation;
- same-day source-card rollout guard;
- venue-specific recovery coverage;
- one visual `🏃 Спорт и движение` heading inside the existing single `Занятия и секции` message.

Sporttia remains one bounded centre-page GET, at most one attempt per local calendar day. The supported parser scope now covers all 15 currently published municipal rows represented by the existing six activity families plus DEPORTE+, and the two psychomotricity groups. There are still no activity-detail requests, internal API calls, occupancy reads, browser automation, or `Abierta/Cerrada` semantics.

Implementation notes / small deliberate deviations from example wording:

- the actual Molivent membership constant is named `MOLIVENT_SOURCE_ACTIVITY_KEYS`, matching the Les Raboses source-membership name;
- DEPORTE+ uses a narrow `_activity_group_order()` exception that returns its single visible group order without weakening `_group_order()` for any other activity;
- Sporttia `registrations` continues to normalize explicit `NUEVAS INSCRIPCIONES` windows only. The April–May DEPORTE+ renewal period is not presented as new-user registration, preserving ADR 0069 semantics;
- the known DEPORTE+ activity mix (`flag rugby`, obstacle course, athletics) is stable resident-facing copy on its activity card; schedule, season, audience, venue, registration action, and medical-certificate requirement remain source-normalized.

No new production-source probe was required for this slice: it uses the Sporttia centre-page contract already validated on 2026-09-16. `guide.py` orchestration, the `sync-guide` schedule, and cron layout are unchanged. No new ADR was added because Deploy 1 does not introduce a new source or architectural contract beyond ADR 0067 and ADR 0069.

### Deploy 2 — notifications — superseded 2026-09-20

The original Sporttia-only `sports_notifications.py` implementation and the
later separate recurring-activity notification path were removed. ADR 0070 is
superseded by ADR 0072.

All recurring course/section sources now feed one
`course_notifications.py` domain state machine. Source adapters stay
independent, while notification projection, semantic grouping, direct internal
card links, first/last registration-day triggers and Telegram
`pending/uncertain/sent` safety are shared.

Public messages are grouped by resident meaning rather than source:
registration closing, registration opening, changed registration dates, new
courses/groups, and other course changes. Different meanings may produce
separate messages in one run; several courses of the same meaning are batched
together.

The first unified run is a silent baseline. Adding a new source is also
baseline-only for its already-existing catalogue, while a genuinely fresh
same-day registration boundary may still notify. Source-row disappearance is
never interpreted as cancellation.

Sporttia retained last-good rows continue to support durable cards, but the
merged catalogue records which source IDs were actually observed in the
current daily fetch. Retained rows therefore cannot create false same-day
opening/deadline or semantic-change notifications.

### Deploy 3 — music activities and linked school — completed 2026-09-17

Implemented as an activity-first extension of the existing linked guide:

- one visual `🎵 Музыка` group inside the existing `🎓 Занятия и секции` message;
- three resident-facing cards: `🎶 Музыкальное развитие и грамота`, `🎤 Вокал и хор`, and `🎷 Музыкальные инструменты`;
- one durable `🎼 Escuela de Música` place card under `📍 Места`, owning map/address, phone/email, website and reverse links to the music cards;
- music activity cards keep only programme/audience/schedule facts, a programme-specific registration action when explicitly open, the internal `📍 Escuela de Música` link, the standard upward navigation link and shared footer; contacts are not duplicated;
- Jardín Musical uses its explicit dated form/window only. The general Escuela
  form is shown only on the shared Escuela de Música card during its explicit
  matrícula window and is never presented as a group-specific CTA;
- published schedule actions link to the official AM Guardamar schedule post, never directly to Google Drive documents that can also contain enrolled-student lists;
- `music_school.py` is a deterministic programme adapter separate from the existing `am_guardamar.py` event semantics;
- the existing 16:30 guide sync performs at most one additional bounded REST GET per Europe/Madrid local day for twelve recently modified AM Guardamar posts, with a 300 KiB response cap and 15-second timeout;
- `state/guide.json` stores only the accepted normalized season/schedule/registration snapshot plus `music_school_last_attempt_day`; raw posts are not persisted;
- same-season last-good schedule/registration facts survive when older posts leave the twelve-post window, while a new season never inherits old links;
- only programme-shaped posts can establish a season, preventing unrelated future-season concert/news text from rolling the school snapshot forward;
- source failure preserves accepted last-good state and linked cards; manual reruns do not repeat a same-day failed/finished source attempt;
- no public music-change notifications are introduced in this deploy.

This contract is recorded in ADR 0071. No new cron row, daemon, database, browser, LLM extraction, PDF/Drive parser, provider framework, or generic navigation layer was added.

### Deploy 4 — recurring municipal/non-sport programs

Add at least:

- `🤝 Муниципальные занятия и мастерские` for the current `Dinamización Social` campaign;
- `📚 Школа для взрослых · EPA` when current-year facts can be taken from an official source without carrying forward old schedules;
- later annual programs such as `Dale Vida a los Años` when a new campaign is published.

Use one bounded official municipal feed/list request as discovery. Fetch detail only for a new/changed matching campaign. If a Google Form/PDF contains extra group detail, fetch it only on campaign change rather than polling it daily.

Do not flatten every workshop into the `Занятия и секции` index. One resident-facing program card may contain several workshops/groups.

### Deploy 5 — holiday programs

Add durable `🏕 Программы на каникулы` as a sibling of `Занятия и секции` at root level and monitor a small explicit allowlist of recurring Guardamar sources.

Current candidates:

- Campus Juanma Ortiz — stable `campusjmortiz.com/inscripcion` page; recurring football camps at Les Raboses;
- Nautilus Nautical Sports — stable Guardamar camp page with spring/summer programs;
- GoSportmadness — Guardamar summer-school pages; discover through a narrow Guardamar/category surface rather than hard-coding a year-specific detail URL;
- official Ayuntamiento/municipal publications — discovery source for municipal holiday programs.

Do not build a generic web crawler. Do not auto-publish Xpert or other ambiguous commercial pages until current year, Guardamar location, dates and registration state are unambiguous.

The holiday card aggregates currently relevant programs. Add per-program Telegram subcards only if actual future content becomes too large for one readable Telegram message.

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

For Deploy 3, prefer a small separate program extractor over changing event semantics. Reusing the same endpoint with one additional bounded daily GET is acceptable and safer than refactoring the existing event catalog solely to save one HTTP request. Consolidate only if measured runtime/network cost justifies it.

### Ayuntamiento / Guardamar municipal site

The official site exposes a WordPress RSS feed (`/feed/`) and publishes campaigns such as `PROGRAMA DINAMIZACIÓN SOCIAL 2026 / 2027` in the normal news surface. Prefer one bounded feed/list request as discovery rather than crawling municipal pages.

On a new/changed matching campaign, fetch its detail once, normalize durable facts, and retain a last-good snapshot. If the registration form contains extra schedule/group detail, fetch it only when the campaign is new/changed; do not poll the form every day.

This source can later discover municipal workshops, EPA notices, `Dale Vida a los Años`, and municipal holiday programs, but each campaign needs an explicit classifier/contract before public output.

### Holiday program sites

Use at most one small stable discovery/page request per approved organizer, once daily while the feature is active or as part of the normal guide sync. Store a compact normalized/fingerprinted snapshot. Fetch extra detail only after a visible change.

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
- newly published approved holiday program/campus after that feature exists;
- explicit cancellation/suspension only when the source actually states it.

Do not notify for raw HTML changes, row reordering, generic `Abierta/Cerrada`, occupancy until a separate contract exists, source failure, or disappearance from the Sporttia centre open-registration surface alone.

First observation after a parser/source rollout is a silent alert baseline so deployment does not falsely announce old activities as newly created. Current time-sensitive registrations may instead receive one deliberate launch overview.

## Current urgent product facts (2026-09-16)

- Sporttia's current 2026/27 registration windows for the targeted municipal sports generally include September and end on 2026-09-30 where explicitly published.
- Jardín Musical (ages 3–6) has an exceptional enrollment extension through 2026-09-17 on the official Agrupación Musical Guardamar site. This is time-sensitive and should not wait for a future automatic change event if Deploy 3 is not ready in time.

## Deferred research

- Sporttia occupancy/status second layer: determine whether all relevant Guardamar capacity/status facts can be obtained by one bounded public request without auth, browser automation or per-activity crawling. Do not change ADR 0069 until that contract is proven.
- Before implementing the municipal-program adapter, make one production-network probe of the Ayuntamiento RSS/list response: final URL, content type, size and encoding.
- Before implementing each holiday source, confirm final URL, redirect policy, response size and the minimum deterministic fields required to distinguish an active current-year Guardamar program from stale history.

## Anti-overengineering rules

- Extend the existing guide/state/recovery patterns; no generic CMS.
- Prefer explicit source-specific classifiers over an abstract plugin/provider framework.
- Keep `guide.py` orchestration-only; source parsing belongs in narrow modules.
- Keep one activities index with visual sections until real content proves another level is needed.
- Create place cards for resident value, not automatically for every venue string.
- One extra bounded GET/day is acceptable when it keeps features isolated.
- No browser automation for ordinary public program discovery.
- No new daemon or source poller; the separate 09:42/11:42 course notification
  schedule is justified by the resident-facing morning timing requirement and
  performs no network collection.
- Persist normalized facts and message IDs, not raw unbounded pages.
- Reuse delivery invariants (baseline, pending, uncertain) without inventing a universal notification framework.
- Update this note after each deploy: mark completed scope, record final source contract, and leave deferred/open items explicit.
