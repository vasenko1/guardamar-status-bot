# Recurring activities and language sources — synchronized 2026-09-18

Status: current research source of truth. Production code for the items in this
document has not been implemented yet. This document supersedes stale planning
conclusions in `2026-09-17-recurring-activities-source-audit.md` where they
conflict.

## Product boundary

Recurring activities are not one-off events.

- one-off competitions/events -> existing local Event catalogs -> Morning/Weekend;
- durable classes/programmes -> linked `🎓 Занятия и секции` guide cards;
- no generic recurring-activity framework, provider registry, YAML source layer,
  database, browser, LLM parser, new daemon, or per-source cron;
- source failure preserves last-good facts;
- first accepted observation is a silent baseline;
- public notifications are only for semantic resident-facing changes;
- normal operation must be unattended. Unknown facts are omitted rather than
  sent to an operator for approval.

The resident-facing entity is the activity/program, not the provider. A club or
school may be the source/contact without becoming the card title.

## Source cost rule

Prefer, in order:

1. zero new requests by reusing an already accepted local snapshot;
2. one tiny structured discovery request;
3. one server-rendered HTML request at a low frequency;
4. detail/form requests only when a discovery fingerprint changes.

Do not poll a Google Form or static club page every day merely because the guide
sync runs daily.

## Current source matrix

| Item | Primary source | Current technical status | Proposed unattended cost | Decision |
| --- | --- | --- | ---: | --- |
| Creative workshops | existing Turismo agenda fetch | Server-rendered text already downloaded by `municipal_agenda.py`; current September 2026 page exposes `TALLERES 2025/2026` and registration facts | **0 new GET/day** | **TECH READY; semantic guard required** |
| Dinamización Social 2026/27 | Ayuntamiento campaign discovery -> detail -> linked Google Form | Detail and Form are ordinary text-readable HTML; no browser/JS/OCR/LLM required | ~1 tiny discovery GET/day; detail/form only on fingerprint change | **READY after production transport probe chooses REST vs RSS** |
| Chess school | Club Dama 2026 page | Plain server HTML; current page exposes school schedule and levels | one low-frequency bounded GET, suggested weekly; no new cron | **TECH READY; production transport probe pending** |
| Tertulia Literaria | official Biblioteca static page | Plain server HTML; durable schedule is explicit | one low-frequency bounded GET, suggested weekly/monthly; no new cron | **TECH READY; production transport probe pending** |
| EPA Spanish | municipal EPA page + current-year forms + reviewed 2026/27 flyer evidence | Official page is current-year, but public machine source does not expose current A1/A2/B1/B1.2 timetable, vacancies or price | piggyback municipal discovery; linked docs only on change | **DEFER dynamic card until current machine-readable offer is sufficient** |
| EPA English / Valencian | same EPA surface | Current 2026/27 detailed offer/timetable not found | same discovery when evidence appears | **DEFER** |
| EOI Guardamar English | Generalitat/EOI | Official section in Guardamar is confirmed, but exact current Guardamar group timetable/vacancies are not yet proven through a stable machine contract | potentially structured Generalitat admission surface | **DEFER until local current contract is proven** |
| Cruz Roja Spanish | Cruz Roja Guardamar | Activity exists, but no first-party current autumn timetable/enrollment surface found | no safe deterministic poller yet | **DEFER dynamic automation** |
| PANGEA / INTEGRA | municipal campaign publications | Good only when an explicit current campaign exists; do not merge the two programmes conceptually | piggyback municipal discovery | **READY AS FUTURE CAMPAIGN CLASSIFIERS; no current autumn card** |
| Educare | provider website | Plain HTML, but current exact group timetable/pricing is not published; commercial-source inclusion is undecided | low | **DEFER product decision** |
| Kairós | provider website | Plain HTML with languages/services, but current exact groups/times/prices are not sufficiently published; commercial-source inclusion is undecided | low | **DEFER product decision** |
| French / German | private candidates mainly Kairós | local direction exists, no production-ready current group facts | — | **DEFER** |

## Creative workshops

Primary source already fetched by production:

`https://guardamarturismo.com/agenda-cultural/`

The current September 2026 agenda text contains:

- `TALLERES 2025/2026`;
- Pintura;
- Cerámica;
- Patchwork;
- Patronaje y confección;
- Talleres de hilo;
- registration 21–25 September, 09:00–20:00;
- Casa de Cultura;
- limited places.

No second collector is justified. Add a narrow deterministic `TALLERES`
extractor to the existing Turismo normalization and let guide sync consume the
accepted local snapshot.

Semantic guard: the agenda is September 2026 but the source block still says
`2025/2026`. Never silently rewrite that label to `2026/27`. Until the
publisher resolves it, either omit the season from resident copy and publish
only explicitly current registration facts after final product review, or fail
closed. The parser must retain the literal source label for diagnostics.

## Dinamización Social 2026/27

Official detail:
`https://www.guardamardelsegura.es/2026/09/07/programa-dinamizacion-social-2026-2027/`

Official linked form:
`https://docs.google.com/forms/d/e/1FAIpQLSdG1kkxJhCHLSd-aZ7j55MFybZMfGHS6FytHgVrOTPo_66Oiw/viewform`

The form is readable with a normal GET without JavaScript execution and exposes:

- main registration period 9–16 September 2026;
- places are limited;
- after the deadline registration may remain open while places remain;
- Guardamar residents have priority;
- Movimiento Consciente — Mon/Wed 11:15–12:15 or 12:15–13:15;
- Uso del móvil — Tue/Thu 09:30–10:30 or 10:30–11:30, from 10 November;
- Arte Reciclado Creativo — Mon/Wed 16:30–18:30;
- Pintura Textil — Fri 16:30–18:30;
- Senderismo para Mayores — Mon/Wed 16:00–17:30 or 17:30–19:00;
- Memoria para Mayores — Tue/Thu 16:30–18:00 or 18:00–19:30;
- Informática para Mayores — Mon/Wed 17:00–18:00 or 18:00–19:00;
- Escuela de Emociones — Wed 09:30–11:00, 14 Oct–16 Dec 2026;
- admission is communicated by phone/email; unsuccessful applicants remain on
  a waiting list; extra groups may be considered if demand/resources allow.

Do not translate `registration may remain open while places remain` into
`places are available now`.

Preferred contract:

1. one Ayuntamiento discovery read during existing guide sync;
2. fingerprint only explicit target campaigns;
3. detail fetch only for new/changed campaign;
4. follow the explicit Google Form link only for new/changed campaign/detail;
5. store compact normalized facts, never raw HTML;
6. preserve last-good on failures.

REST vs RSS is intentionally not chosen yet. Production probe should compare
final URL/MIME/size and choose the smaller stable contract.

## Chess

Primary source:
`https://ajedrezdamadeguardamar.com/cuotas/`

The current 2026 page is server-rendered and explicitly states:

- `ESCUELA DE AJEDREZ`;
- Tuesday and Thursday;
- 16:00–20:00;
- levels `INICIACIÓN–AVANZADO`;
- contact through the school/club source.

The card remains `♟️ Шахматы`, not a provider advertisement.

The earlier plan of no automatic source reads at all is superseded by the
unattended-operation requirement. A daily GET is still unnecessary. Use the
existing daily guide invocation but condition the source read on a low-frequency
last-attempt date (for example weekly). This adds no cron/daemon and keeps
network cost negligible while allowing autonomous source turnover.

A narrow `chess_school.py` adapter is still appropriate; do not create a
generic provider engine.

## Tertulia Literaria

Official source:
`https://www.bibliotecaspublicas.es/guardamardelsegura/actividades-programas/Tertulia-Literaria-de-Guardamar.html`

The durable official page states that the group meets every Tuesday 11:00–13:00
in the auditorium of the Municipal Public Library and works by sharing texts and
literary creation.

This is a recurring group, not a dated Event. Existing `library_agenda.py`
should remain responsible for dated agenda items; do not force the static
Tertulia through the event pipeline.

As with chess, unattended operation favors a very low-frequency static-page
check rather than manual seasonal revalidation. No new cron is needed.

## EPA 2026/27

Official mutable page:
`https://www.guardamardelsegura.es/2024/07/24/epa-escuela-de-personas-adultas-curso-2024-2025/`

Despite its historical slug, it currently displays `CURSO 2026 / 2027` and
links 2026/27 enrollment forms.

The public non-regulated form is generic: it asks the applicant to enter the
course name and notes that the applicant has been informed separately about
schedule/dates/duration. It also lists proof of course payment among possible
documents. That is not evidence of a particular Spanish-course price.

Reviewed 2026/27 Spanish evidence confirms A1, A2, B1 and B1.2 for adults 18+,
with 2–11 September enrollment at Casa de Cultura and the specified identity
documents/photo. The flyer says successful completion plus 85% attendance gives
A2 certification.

Do not claim:

- a current timetable not present in current-year machine evidence;
- current post-deadline vacancy;
- free or paid status;
- DELE equivalence.

Because normal operation must be unattended, the reviewed flyer is useful
research evidence but is not by itself a sufficient long-lived dynamic source
contract. Do not implement the language card until the current public machine
surface can sustain the facts the card needs.

## EOI Guardamar

The Guardamar section is real. Official 2026 Generalitat documentation lists
EOI Torrevieja's Guardamar del Segura section at C/ Molivent in Guardamar.
It must not be described as merely a Torrevieja option.

The latest research also found current 2026/27 EOI admission dates, but the
general EOI schedule/admission material does not prove which exact groups,
times or vacancies belong specifically to the Guardamar section.

The Generalitat vacancy application is a promising structured source, but its
Guardamar-specific query contract still needs to be proven before code. Do not
use third-party pages as the runtime source of truth.

## Cruz Roja Spanish

Cruz Roja Guardamar is a real local provider and historical/current evidence
shows Spanish-for-foreigners activity, but no stable first-party public surface
was found for current autumn 2026 days, times, levels, vacancies or enrollment.

A generic Cruz Roja training catalog exists, but it does not currently expose
this Spanish programme as a deterministic local course record. Therefore do
not build a scraper from community mirrors or infer schedule from older posts.

## PANGEA and INTEGRA

Keep them separate.

INTEGRA published a March 2026 basic–intermediate conversation course. It is a
social-inclusion programme for people in / at risk of social exclusion, not an
ordinary open language school.

PANGEA is the municipal office for migrants and has run campaign-driven
integration/language activities. Older Integra-T pages have misleading date
metadata and must not be treated as proof of current September activity.

Both are good future explicit classifiers on the same municipal discovery
surface. Show a card only when an explicit current campaign/intake exists.

## Private providers

Educare currently publishes, in plain HTML, English for school ages,
Cambridge/Trinity preparation A1–C1, and Spanish for foreigners, plus contact
and center opening hours. It does not publish a stable exact group timetable or
price.

Kairós currently publishes English, German, French, Spanish for foreigners,
official-exam preparation, conversation classes, Valencian C1 preparation,
small groups, contact and center opening hours. It likewise does not expose a
stable current exact group timetable/pricing contract.

Even technically easy HTML does not automatically make these sources suitable
for the municipal guide. Product inclusion of commercial academies remains a
separate decision.

## User-facing information architecture

Keep one existing `🎓 Занятия и секции` index. Visual headings do not create a
new Telegram state/navigation layer.

Confirmed recurring card concepts:

- `♟️ Шахматы`;
- `🎨 Творческие мастерские`;
- `🤝 Муниципальные занятия и мастерские`;
- `✍️ Литературное творчество`.

Language architecture is language-first rather than provider-first:

- `🌍 Языковые курсы`
  - Spanish -> EPA, Cruz Roja, current PANGEA/INTEGRA campaigns;
  - English -> EOI Guardamar, EPA, possible private child options only if the
    commercial-provider rule is explicitly opened;
  - Valencian -> EPA and only later verified alternatives;
  - French/German -> no production-ready public/municipal regular offering.

Do not implement this hierarchy until the exact initial card set has enough
current source evidence. One reviewed Spanish snapshot alone does not justify
shipping a new hierarchy.

## Notifications and recovery

Every implemented recurring card must preserve existing guide invariants:

- edit existing message;
- MESSAGE-NOT-MODIFIED is success;
- MESSAGE-NOT-FOUND recreates the card and updates state;
- reconcile all links after recreation;
- source failure preserves last-good;
- first observation is silent;
- notify only semantic changes: new current program/group/season, schedule,
  venue, audience/age, registration window/deadline, explicit until-full,
  cancellation or meaningful participation conditions;
- do not notify on HTML churn, row order, source outage, disappearance alone or
  generic open/closed labels.

No new generic notification framework is justified. Reuse invariants from the
existing sports notification design.

## Remaining production verification

The exact read-only script is stored in
`research/2026-09-18-recurring-source-production-probe.md`.

A single Termux probe is still required before implementation to
record final URL, HTTP status, MIME, bytes and time for:

- Ayuntamiento RSS feed;
- Ayuntamiento WordPress REST posts endpoint;
- Dinamización detail;
- linked Google Form;
- Turismo agenda;
- chess source;
- Tertulia source;
- EPA page;
- optionally the Generalitat EOI vacancy entry surface.

After that probe:

1. choose REST or RSS for the one municipal discovery request;
2. implement Chess + Tertulia as low-frequency source-specific guide adapters;
3. extract Workshops from the already-fetched Turismo page with zero new GETs;
4. implement Dinamización using one discovery adapter and changed-detail/form
   reads;
5. keep language cards deferred until their current source contracts are
   sufficient.

No production code should be changed before this probe is reviewed.
