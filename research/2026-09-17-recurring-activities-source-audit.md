# Guardamar recurring activities source audit — 2026-09-17

## Goal

Decide which newly investigated recurring activities/programs are suitable for
the linked `🎓 Занятия и секции` guide and, specifically, which sources are
cheap, fast, deterministic and stable enough for unattended collection on the
Android/Termux production device.

This audit is deliberately separate from sports competitions. Competitions are
normal `Event` facts and go through Morning Digest / weekend event catalogs.
Recurring classes, courses and season-long municipal programmes belong here.

## Acceptance rule

A source is ready for automatic guide use only when the bot can determine the
current Guardamar programme without browser automation or inference. Prefer:

1. one small structured/API/feed request;
2. one stable server-rendered HTML page;
3. a detail/form request only when the discovery page visibly changes.

Do not publish a recurring card from an old season label, an undated generic
page, or a source that requires guessing whether a programme is still active.
Source failure preserves last-good facts; it never turns into a guessed update.

## Current decisions

| Candidate | Current evidence | Automation cost | Decision |
| --- | --- | --- | --- |
| Chess school | Club Dama 2026 page explicitly says the chess school runs Tuesdays and Thursdays 16:00–20:00, levels `Iniciación–Avanzado`; normal server HTML | One bounded GET/day inside existing 16:30 guide sync; no browser/API | **Ready after one production transport probe** |
| Dinamización Social 2026/27 | Official Ayuntamiento post dated 7 Sep 2026 links the current registration form; form states registration 9–16 Sep, continuation until full if places remain, and contains all current workshops/groups/times | One bounded municipal discovery request; fetch detail/form only for new/changed campaign | **Source contract is strong; next municipal-program slice** |
| EPA 2026/27 | Official Ayuntamiento EPA page is currently titled `CURSO 2026 / 2027` and links the current regulated/non-regulated enrolment forms | Discovery is cheap; public page does not itself expose enough timetable/course detail | **Keep as candidate; do not invent schedule** |
| Casa de Cultura workshops | Existing Turismo agenda fetch already exposes the workshop block and registration facts | Zero extra discovery request because `municipal_agenda.py` already fetches the page | **Monitor only now**: September 2026 page labels the block `TALLERES 2025/2026`, so season is ambiguous/stale |
| Biblioteca Club de lectura / Tertulia | Official library site has durable pages for these programmes, and the existing library adapter already reads the current agenda | No new collector needed | **Monitor only**: current 2026 agenda has exhibitions/cinema but no current club timetable/registration |
| EOI / English in Guardamar | Municipality links to Escuela Oficial de Idiomas, and regional admission information exists | Exact Guardamar-section current timetable/registration endpoint has not yet been proven stable | **Defer** until a reliable official endpoint is validated |
| Museum / guided heritage activities | Current Turismo agenda provides dated guided visits and exhibitions | Already belongs to existing event pipeline | **Do not create recurring course cards** |
| Nautilus | Commercial operator pages describe camps/courses rather than a stable season-long group timetable | Would require programme-specific interpretation | **Exclude from recurring activities**; keep for holiday-program research |
| Private academies / associations not backed by a stable current page | Varies | High risk of stale/manual facts | **Do not automate yet** |

## Chess — proposed implementation

Source page:
`https://ajedrezdamadeguardamar.com/cuotas/`

Current 2026 page explicitly states:

- `ESCUELA DE AJEDREZ`;
- Tuesdays and Thursdays;
- 16:00–20:00;
- levels from `INICIACIÓN` to `AVANZADO`.

The page also exposes club contact details, but the resident-facing activity
card should remain activity-first. Do not make the provider/operator the card
title. Use `♟️ Шахматы`; show only useful schedule/level/contact/place facts.

Implementation shape:

- `chess_school.py`, narrow deterministic HTML adapter;
- one bounded GET at most once per Europe/Madrid day inside existing
  `sync-guide` at 16:30;
- compact normalized snapshot in `state/guide.json` with
  `chess_school_last_attempt_day`;
- last-good snapshot on source failure;
- one durable `chess` activity card linked from `Занятия и секции`;
- no new cron, daemon, database, browser, generic provider layer or LLM parser;
- no public change notification in the first slice.

Before implementation, verify from production: final URL, HTTP status,
content type, response size, redirect and that the expected school markers are
present.

## Dinamización Social 2026/27 — source contract

Official detail page:
`https://www.guardamardelsegura.es/2026/09/07/programa-dinamizacion-social-2026-2027/`

The linked current Google Form is readable as ordinary HTML and currently
contains deterministic programme facts, including:

- registration window `9–16 September 2026`;
- limited places; after the deadline registration may remain open until places
  are filled;
- `Movimiento consciente` — two Mon/Wed morning groups;
- `Uso del móvil` — two Tue/Thu morning groups, from 10 November;
- `Arte reciclado creativo` — Mon/Wed 16:30–18:30;
- `Pintura textil` — Fri 16:30–18:30;
- `Senderismo para mayores` — two Mon/Wed afternoon groups;
- `Memoria para mayores` — two Tue/Thu afternoon groups;
- `Informática para mayores` — two Mon/Wed afternoon groups;
- `Escuela de emociones` — Wed 09:30–11:00, 14 Oct–16 Dec 2026.

This is a good automation target because the official municipal post gives the
campaign identity/year and the linked form gives the actual current group
facts. The form should **not** be polled daily. Discovery should fingerprint the
municipal post/link; fetch the form when the campaign/link changes, normalize
facts, and retain them locally.

Preferred discovery order after production verification:

1. bounded Ayuntamiento WordPress REST list if available and stable;
2. otherwise bounded official RSS feed;
3. detail page only for a new/changed matching campaign;
4. linked Google Form only for a new/changed campaign/detail fingerprint.

One resident-facing card `🤝 Муниципальные занятия и мастерские` can contain
all current groups initially. Do not create a Telegram card per workshop.

## EPA 2026/27

Official page:
`https://www.guardamardelsegura.es/2024/07/24/epa-escuela-de-personas-adultas-curso-2024-2025/`

Despite the historical URL slug, the page title and linked enrolment documents
are currently updated to `CURSO 2026 / 2027`. That makes it useful as an
official current-year discovery source, but the visible HTML does not provide a
complete current timetable/offer.

Therefore:

- classify/fingerprint the current-year EPA page through the same municipal
  discovery adapter;
- fetch a linked form/document only when the current-year link changes;
- publish only fields explicitly recoverable from the current official
  material;
- do not carry 2025/26 timetable/course names forward merely because the slug
  is old.

EPA is not a blocker for the chess or Dinamización slices.

## Casa de Cultura workshops

The existing municipal/Turismo event collector already downloads
`https://guardamarturismo.com/agenda-cultural/`, so a second daily request is
unnecessary. The September 2026 page currently says:

`TALLERES 2025/2026 — Pintura, cerámica, patchwork, patronaje y confección,
talleres de hilo; inscripciones 21–25 septiembre 09:00–20:00; Casa de Cultura;
plazas limitadas.`

The registration dates look current while the season label does not. Fail
closed: keep this as monitored evidence and do not publish a 2026/27 recurring
card until the official source resolves the season ambiguity.

If/when it becomes unambiguous, extract it from the **already fetched** Turismo
agenda/catalog rather than adding another network collector.

## Biblioteca

The official Guardamar library currently exposes four upcoming agenda items:
exhibitions and Monday cinema. Its durable programme navigation mentions
`Club de lectura` and `Tertulia literaria de Guardamar`, but no current 2026/27
schedule/registration was found there.

The project already has `library_agenda.py` with one bounded official list
refresh and changed-detail reads. Therefore there is no source gap to solve
with another adapter. If a current reading-club/session appears in the agenda,
it should first enter the normal event catalog; only create a recurring guide
card when the official site provides durable current-season participation
facts.

## What to implement next

After the federation-event branch passes production tests:

1. production-probe the chess page and Ayuntamiento REST/RSS discovery endpoints;
2. implement the chess source/card as a small guide-sync slice;
3. implement one municipal-program discovery adapter and the current
   Dinamización Social card;
4. keep EPA as the next classifier on the same municipal discovery adapter,
   only after current offer/timetable facts are proven;
5. leave Casa de Cultura workshops, library clubs and EOI in monitored/deferred
   state until their current-season contracts are unambiguous.

This sequencing intentionally does not add a generic recurring-activities
framework. Each source gets only the narrow parser/state needed for facts we
can verify today.