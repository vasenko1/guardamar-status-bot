# 0071: Model music as activity cards linked to a shared school place card

- Status: Accepted
- Date: 2026-09-17

## Context

The linked guide already treats recurring activities as resident-facing entities and durable places as shared destinations. Agrupación Musical de Guardamar publishes both public events and school/programme information on the same WordPress site. The existing event adapter intentionally rejects `matrícula`, `curso`, `horarios`, `asignaturas` and similar programme posts, so broadening that event pipeline would mix two different semantics.

Music must also scale beyond one school: the same activity may later be offered by another school or studio. A provider-first card would duplicate course categories and force residents to browse organizations instead of the activity they want.

## Decision

Deploy 3 adds one visual `🎵 Музыка` group inside the existing `🎓 Занятия и секции` index and three resident-facing activity cards:

- `🎶 Музыкальное развитие и грамота`;
- `🎤 Вокал и хор`;
- `🎷 Музыкальные инструменты`.

The activity card is the primary user-facing entity. Provider/location details are represented separately by one durable `🎼 Escuela de Música` place card under `📍 Места`. Every music activity links to that card through its `📍 Escuela de Música` row. The school card owns address, map, phone, email, site, reverse activity links, `⬅️ К списку мест`, and the shared footer. Activity cards do not duplicate contacts; they keep only programme name/audience, compact schedule facts, an explicit programme-specific registration action when currently valid, the school link, `⬅️ К занятиям и секциям`, and the shared footer.

The source adapter is deliberately separate from `am_guardamar.py`. Once per Europe/Madrid local day, the existing guide sync performs one bounded GET of the twelve most recently modified public WordPress posts with only `id,date,modified,link,title,content`. The response is limited to 300 KiB with a 15-second timeout and a narrow HTTPS host/path policy. No LLM, browser, PDF parser, Google Drive parser, database, daemon, new cron entry, or extra service is introduced.

Only programme-shaped posts can establish a school season. An unrelated concert or news post that happens to mention a future season cannot roll the programme snapshot forward. Current explicit registration windows are parsed only when a matching official form is present. Same-season last-good schedule/registration facts may survive after an older source post leaves the recent-post window; a new season never inherits old-season links.

The normalized snapshot lives in existing `state/guide.json` and stores only observation time, school season, the safe official schedule-post URL, and explicit Jardín/general-school registration windows/forms. The guide records `music_school_last_attempt_day` before network I/O so manual reruns cannot hammer the source after a timeout or parse failure.

Schedule links point to the official AM Guardamar schedule post, not to its linked Google Drive documents, because those documents may also contain enrolled-student lists. The activity renderer never deep-links those files. The general Escuela matrícula form is retained as normalized source evidence but is not presented as if it were a group-specific enrolment action. Jardín may show `📝 Записаться` only while its explicit dated programme-specific window is open; after the end date the action disappears without claiming cancellation or availability.

## Consequences

- The existing `Занятия и секции` message remains the only activity index; `🎵 Музыка` is visual grouping only.
- One provider can serve several activity cards without duplicating address/contact details.
- A future second school/studio can be added inside the relevant activity model without creating provider-first duplicate categories.
- The school place card participates in the existing recoverable linked-message graph; if it is recreated, music activity links converge to its new Telegram message ID.
- Source failure preserves accepted last-good programme state and does not remove existing cards.
- Runtime source cost is one additional small WordPress REST GET at most once per local day inside the existing guide sync.
- No public change-notification feature is added in Deploy 3; this slice only maintains the linked guide.
