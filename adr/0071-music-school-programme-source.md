# 0071: Publish music activities from a bounded AM Guardamar programme snapshot

- Status: Accepted
- Date: 2026-09-17

## Context

The linked Guardamar guide already models recurring resident-facing activities separately from their venues and source rows. The Agrupación Musical de Guardamar publishes current school enrolment and group-schedule notices on its public WordPress site. The project also has an AM Guardamar event adapter, but that path deliberately rejects `matrícula`, `curso`, `horarios`, `asignaturas` and similar programme material so school administration cannot be misclassified as public events.

Residents search primarily for an activity (early music/language, vocal/choir, instruments), not for the publishing organisation. Repeating the same school address, phone and email in every activity card would make the guide noisy and difficult to extend when another studio offers the same type of activity.

The phone remains a low-power Termux host. The feature must fit the existing 16:30 one-shot guide sync, atomic JSON state and bounded Telegram reconciliation without another daemon, cron entry, database, browser or generic provider framework.

## Decision

Add a narrow `music_school.py` source adapter. It performs at most one bounded HTTPS GET per local calendar day to the already-proven AM Guardamar WordPress posts endpoint, requesting twelve recently modified posts and only `id,date,modified,link,title,content`.

The adapter uses deterministic parsing only; no Gemini/LLM and no PDF/Google Drive parsing. It normalizes only seasonal facts needed by the guide:

- current school-course label;
- explicit Jardín Musical registration window and its dedicated registration URL;
- explicit general Escuela de Música registration window (retained for source state, not presented as a group-specific CTA);
- the official AM Guardamar post that publishes current group schedules.

The schedule action links to the official AM Guardamar post, not directly to its Google Drive documents, because those documents also contain enrolled-student lists. The guide does not fetch, store or parse those documents or any student data.

Same-season fields use last-good retention when an older relevant post falls out of the twelve-post discovery window. A newly observed season does not inherit the previous season's schedule or registration links. Source failure preserves the previous accepted snapshot. The guide marks the local attempt date before network I/O, matching the existing Sporttia anti-hammering pattern.

Stable, reviewed school facts (venue identity, address, contact, Jardín age/load, Lenguaje Musical age/load and the broad current instrument families) remain explicit user-facing copy rather than a generic content-extraction system.

## Information architecture

Create one durable place card `🎼 Escuela de Música` under `📍 Места`. It owns:

- Google Maps action and address;
- copyable phone and email;
- school website;
- reverse links to music activity cards.

Create three resident-facing activity cards under one visual `🎵 Музыка` section of the existing `🎓 Занятия и секции` index:

1. `🎶 Музыкальное развитие и грамота` — Jardín Musical, Lenguaje Musical, Lenguaje Musical para Adultos;
2. `🎤 Вокал и хор` — Técnica Vocal / Coro;
3. `🎷 Музыкальные инструменты` — wind families plus the other explicitly published instrumental families.

Each activity row links its `📍 Escuela de Música` venue to the internal place card. Activity cards do not repeat phone/email. A direct `📝 Записаться` action is shown only when an explicit registration window is currently open and the form is specific to that programme; currently this applies to Jardín Musical. The general school enrolment form is not presented as if it were a group-specific form.

Every final card keeps the existing UX contract: one upward `⬅️` navigation link immediately before the shared `📣 обЪявления Гуардамар` footer.

## Consequences

- One additional small WordPress GET per day is accepted to keep programme semantics isolated from the existing event adapter.
- No category-ID discovery, detail-page crawling, PDF parser, Google Drive reader, browser automation, database, plugin/provider abstraction or new scheduler is introduced.
- Music source data is one optional validated top-level snapshot in `state/guide.json` plus one local attempt-day field.
- `pinned_guide.json` continues to own only managed Telegram message IDs/recovery state.
- The existing bounded reconciliation graph remains responsible for recreating a deleted school/activity card and relinking affected parent/child cards.
- If another provider later offers the same activity, it can be added as another explicit provider/venue block inside the relevant activity card; no organisation-first navigation hierarchy is required.
