# Activities and Programs

Status: planning / architecture-audited — 2026-09-16

This note is the living product/technical plan for the linked Guardamar guide. It records agreed scope, source contracts, information architecture, implementation gaps and deployment order so future work does not depend on chat history.

It is intentionally not an ADR. ADRs record accepted architectural decisions after a source/implementation contract is proven; this file tracks planned work and is updated as each slice is implemented, deferred or rejected.

## Documentation roles

- This file (`14_Activities_and_Programs.md`) is the single living implementation ledger for activities/programs.
- `09_Roadmap.md` remains high level; do not duplicate item-by-item implementation detail there.
- `06_Data_Sources.md` is updated only when a source role is actually approved/implemented.
- `11_Pinned_Message_Content.md` records final resident-facing guide copy/rules. Its legacy root section still describes the old two-item root and must be brought in sync when the next guide-content implementation lands; do not use that old root description to override current code/ADRs.
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
🎼 Школа музыки

🤝 Другие программы
🧩 Муниципальные занятия и мастерские
📚 Школа для взрослых · EPA
```

This is presentation grouping only; it does not create category messages or category state. Introduce a new intermediate Telegram card only after real content proves that one index or one program card is too long/hard to scan, not pre-emptively.

### Card granularity

Use one durable card per resident-recognizable activity/program, not one card per source row or timetable group.

- Several Sporttia `turno` rows for the same activity stay inside one activity card.
- `Школа музыки` may contain Jardín Musical and the school’s related enrolment facts/offer inside one card initially.
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
- Centro Social Juvenil.

Future places such as CEIP Reyes Católicos or the music school should receive cards only when their actual guide value justifies one, not merely because a source mentions the venue.

## Code architecture audit

The current architecture is suitable for the planned expansion and should be extended, not replaced. Keep the existing one-shot Termux model, atomic JSON state, source-specific adapters and linked-message reconciliation.

### Gap 1 — `SPORT_ACTIVITY_KEYS` is overloaded

Today one tuple effectively means several different things at once: Sporttia parser scope, valid snapshot keys, source-managed Telegram cards, rows in `Занятия и секции`, and all activities assumed to belong to Palau Sant Jaume. Recovery tests currently encode the same all-sports-at-Palau assumption.

That accidental coupling must be removed before adding Les Raboses and Molivent, but without introducing a Place/Activity relation engine.

Use a few explicit constants by responsibility, for example:

```python
SPORTTIA_ACTIVITY_KEYS = (... existing ..., "deporte_plus", "psychomotor")
PALAU_ACTIVITY_KEYS = (... existing six ...)
LES_RABOSES_SOURCE_ACTIVITY_KEYS = ("deporte_plus",)
MOLIVENT_ACTIVITY_KEYS = ("psychomotor",)
```

Football remains a durable static activity and is not added to Sporttia source keys.

The exact constant names may differ, but source ownership and venue membership must no longer be represented by the same tuple.

### Gap 2 — venue rendering only knows Palau

`_venue_markup` currently recognizes only `Palau Sant Jaume`; other venues are plain text. Extend it with a tiny explicit prefix-to-guide-link resolver for the few supported durable places (Palau, Les Raboses, Molivent). Preserve any source detail after the known venue name as plain text, for example field/room information.

This is a presentation lookup, not a generic place ontology. Unknown venues remain escaped plain text or an explicit map link when a feature deliberately supplies one.

### Gap 3 — source-card creation must not manufacture empty cards during rollout

`publish_pinned_guide` currently loops every source activity key and upserts a card. When a new classifier key is deployed after that day’s single Sporttia attempt has already happened, the saved catalogue may not yet contain the new activity. Do not create a misleading empty new card solely because the code knows the key.

For a newly supported source-managed key, create/recreate the card only when either:

- selected current/future source groups exist; or
- an already-known stable message is being recovered and the current last-good catalogue still supports it.

Do not add an extra Sporttia fetch merely to solve deployment timing.

### Gap 4 — recovery tests assume one venue

Rewrite recovery expectations around actual owners:

- a Palau activity relinks `Занятия и секции` and Palau;
- DEPORTE+ relinks `Занятия и секции` and Les Raboses;
- psychomotor relinks `Занятия и секции` and CEIP Molivent;
- deleting a place relinks only the activities/cards that point to that place;
- football is recovered as a durable static card, not a Sporttia-managed card.

Keep the existing bounded reconciliation passes. Do not build a general graph database or dependency engine.

### Gap 5 — `guide.py` must stay an orchestrator

`guide.py` already coordinates Aqualider, Sporttia, Wi-Fi, pinned reconciliation and the pool-season notice. Do not place all future HTML/RSS/WordPress parsing into this module.

Follow the existing project pattern:

- source-specific access/normalization in small modules such as `sporttia.py`, `am_guardamar.py`, and future narrow modules for municipal/holiday programs;
- `guide.py` calls them sequentially, handles last-good state and then reconciles Telegram cards.

No plugin framework, provider registry, dependency injection container or generic source scheduler is needed.

### Gap 6 — the existing guide state can grow safely

Keep `state/guide.json` as the small atomic guide/source state. Add optional, independently validated top-level normalized snapshots as features land (for example music/municipal/holiday catalog state) instead of introducing a database or one file per activity.

Do not persist raw pages. Preserve last-good normalized facts on source failure. New optional keys must be backward-compatible with existing state.

Notification delivery state may be separate when it needs explicit `pending/uncertain` semantics; do not overload `pinned_guide.json`, whose job is message IDs/media graph state.

### Gap 7 — notification semantics should copy the proven pattern, not its module

`transport_notifications.py` already proves the useful delivery ideas: silent first baseline, semantic diffs, batching, atomic pending state, and `uncertain` before `sendMessage` because Telegram has no idempotency key.

Sports/program notifications should use those same small invariants but should not import or generalize transport notification internals into a universal notification framework.

## Termux/runtime budget

Keep the existing daily `sync-guide` one-shot at 16:30 Europe/Madrid. It runs as one short process, writes a bounded rotating log and exits. New guide/program collectors should normally run inside this same invocation.

Accept a handful of small sequential bounded GETs per day. On this project, engineering isolation is more valuable than saving 1–4 HTTP requests/day. Do not add a daemon, resident watcher, thread pool, browser automation, database, message broker or new cron merely to avoid a few requests.

A separate schedule is justified only if a real product requirement needs a materially different time of day. Registration/program guide discovery does not currently justify one.

## Deployment sequence

### Deploy 1 — sports core / linked guide only

Keep this deployment limited to the existing linked-guide and Sporttia architecture.

Add:

- `Complejo Deportivo Les Raboses` as a durable place card;
- `CEIP Molivent` as a durable place card;
- `DEPORTE +` from the existing Sporttia centre read;
- `Психомоторика` from the existing Sporttia centre read (two current groups at CEIP Molivent);
- `Футбол` as a durable Guardamar Soccer C.D. activity card linked to Les Raboses; do not pretend it is Sporttia-managed;
- internal venue links matching the existing Palau UX;
- explicit source/venue key separation described above;
- source-card rollout guard described above;
- venue-specific recovery tests;
- visual grouping in `Занятия и секции` only if it improves the now-longer index; no new category cards.

Current Sporttia target after this deploy: cover all 15 currently published municipal rows from the one existing bounded centre-page GET.

Do not add in Deploy 1:

- a second Sporttia source;
- per-activity Sporttia requests;
- occupancy `Alumnos X/Y`;
- interpretation of generic Sporttia `Abierta/Cerrada`;
- automatic public sport-change notifications;
- music/social/holiday program source code.

### Deploy 2 — sports notifications

After Deploy 1 has been verified in production, add semantic sports notifications as a separate public-side-effect slice.

Reuse the existing 16:30 source observation; do not add a poll or cron. Compare normalized previous/current facts, batch multiple material changes into one calm message, and use a silent baseline plus uncertain-delivery protection comparable to the proven transport notification pattern.

Date-triggered registration-opening/deadline notices need compact dedupe state. They do not require another source request.

A deliberate one-time launch overview may be used for registrations already open before the notification feature was deployed; do not mislabel old activities as newly discovered.

### Deploy 3 — music school

Add `🎼 Школа музыки` under recurring activities.

The project already has a bounded Agrupación Musical Guardamar WordPress REST adapter reading twelve recently modified posts. Its event path deliberately rejects `matrícula`, `curso`, `horarios`, `plazas`, etc. For the program feature, prefer a small deterministic program extractor over broadening event semantics.

One additional bounded daily GET to the same endpoint is acceptable if that keeps event and programme logic isolated. Refactor shared fetching only later if measured cost justifies it.

Track only explicit current facts: Jardín Musical/other school offer, enrollment window, audience/age, schedule facts, contact and registration URL.

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

## Open research, not blockers for Deploy 1

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
- No new daemon/cron when the existing daily guide/catalog refresh can carry the work.
- Persist normalized facts and message IDs, not raw unbounded pages.
- Reuse delivery invariants (baseline, pending, uncertain) without inventing a universal notification framework.
- Update this note after each deploy: mark completed scope, record final source contract, and leave deferred/open items explicit.