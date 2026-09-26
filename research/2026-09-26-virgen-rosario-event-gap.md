# Virgen del Rosario event gap — source and runtime investigation

Investigation date: 26 September 2026 (Europe/Madrid).

## Incident

The Saturday 26 September weekend/event catalogue missed three important
patronal acts later reminded by the Mayor on the same day:

- 17:00 — Gran bingo de regalos, bajos del Ayuntamiento;
- 19:50 in the programme (19:45 in the Mayor's same-day reminder) — traslado
  de la Virgen del Rosario;
- 20:00 — Santa Misa and presentation of the fiestas poster.

This was not a late-announcement problem. The event information existed well
before the day of publication.

## Primary and supplemental source timeline

### Ayuntamiento de Guardamar — primary official programme

On 16 September the municipality published **Fiestas en honor a la Virgen del
Rosario 2026**:

https://www.guardamardelsegura.es/2026/09/16/fiestas-en-honor-a-la-virgen-del-rosario-2026/

Its full-size official programme image is:

https://www.guardamardelsegura.es/wp-content/uploads/2026/09/PROG.-todo-Virgen-Rosario-2026-2122x3000.jpg

The programme already contains the 26 September Bingo, traslado and
Misa/cartel rows. The municipal monthly cultural agenda/MUPI does not contain
the complete patronal programme, so the ordinary monthly source cannot be
treated as a complete festival catalogue.

### Guardamar Turismo — primary official text

Turismo published a separate article:

https://guardamarturismo.com/fiestas-de-la-virgen-del-rosario-de-guardamar-2026/

The article identifies the 26 September block (Bingo Benéfico, traslado,
Santa Misa and presentation of the poster) and subsequent patronal dates. This
is the same public WordPress surface already used by the bot for the narrow
Fiestas del Campo adapter. The current runtime adapter, however, searches and
accepts only **Fiestas del Campo**, so Rosario cannot enter through it.

The broader source pattern is not unique to Rosario: Turismo also publishes
separate programme articles for large Guardamar events such as Moros y
Cristianos, Hogueras, Feria del Comercio and Fiestas del Campo. Generic,
bounded discovery of official programme-shaped articles is therefore a
separate follow-up from the Todo correctness repair.

### Todo Cultura Vega Baja — supplemental text copy

The already integrated supplemental source has a detailed Guardamar page:

https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-gran-bingo-de-regalos-a-beneficio-de-las-fiestas-de-la-virgen-del-rosario-dentro-de-los-actos-de-las-fiestas-patronales-en-honor-a-la-virgen-del-rosario-organizados-2/?occurrence=2026-09-26

Its visible event identity is 26 September at 17:00. The body also contains
the dated 26 September section:

- 17:00 — Gran bingo;
- 19:50 — traslado;
- 20:00 — Misa and presentation of the poster.

The introductory prose additionally says that the patronal programme runs from
19 September through 18 October. Those range endpoints are the values that the
old metadata-only date discovery persisted.

## Production evidence and exact failure chain

The production Todo state contained the Bingo publication (and a duplicate-like
second WordPress record) before the event. Both candidates were local and had:

- metadata dates: `2026-09-19`, `2026-10-18`;
- `processed_dates=[]`;
- `detail_checked=false`.

The incremental cursor had already advanced beyond the Bingo publication's
22 September modification time, proving that the metadata record had been seen.

The old collector selected detail pages by dates extracted from only REST
`title + excerpt`. For the long Rosario page this interpreted the whole-fiesta
range endpoints as event dates. On 26 September the 19 September endpoint was
past and the 18 October endpoint was only a horizon date, while many older
Guardamar candidates had an unprocessed date inside the current seven-day
window. The Bingo candidate therefore ranked behind the current-window backlog.

The detail budget was bounded to six candidates, and repeated Todo runs from
22–25 September reported incomplete extraction. The previous fail-closed
transaction preserved the old Todo source state whenever any selected programme
was incomplete. Successful candidates therefore stayed pending and repeatedly
occupied the front of the queue. The Friday 19:15 fresh event refresh ran, but
Todo was incomplete; the weekend digest then published successfully from the
still-incomplete normalized catalogue. This excludes stale scheduling,
Friday-refresh timing and the downstream renderer as root causes.

## Root cause

The miss is a cascade of three assumptions:

1. the monthly official cultural agenda is sufficiently complete for large
   city fiestas;
2. dates in a Todo REST excerpt are reliable occurrence dates before reading
   the full event document;
3. rolling back the whole Todo incremental state is the safest response to one
   incomplete selected programme.

Each assumption was individually conservative, but together they made an
already-discovered local page invisible to the bounded current window.

## Accepted Todo repair

The Todo correctness repair remains bounded and uses existing mechanisms:

- metadata dates become **hints**;
- explicit dated headings in a downloaded detail page replace those hints;
- one of the existing six detail slots is ordered first for an unchecked local
  candidate in the 44-day horizon, with no increase in limits;
- dated standalone pages emit existing deterministic `event_rows`, so the
  existing completeness/recovery logic and raw-row session grouping apply;
- verified detail/date discovery may persist after incomplete extraction;
- processed dates/chunks advance per completed candidate, while failed
  candidates retain their prior extraction progress;
- parser v19→v20 preserves the just-added raw-session-row work instead of
  forcing another full reset.

Limits remain:

- `MAX_CANDIDATES = 6`;
- `MAX_DOCUMENTS_PER_REQUEST = 4`;
- `MAX_PROGRAMS_PER_WINDOW = 3`.

No dependency, daemon, scheduler, browser automation or generic cache is added.

## Interaction with multi-session events

Main already derives compact session identity from raw Todo `event_rows`
before translation. The repair deliberately does not change that grouping
logic. It only supplies raw rows for dated standalone pages too.

Explicit `turno / sesión / pase` families such as the museum Escape Room can
therefore use the existing session identity. Rosario's independent Bingo,
traslado and Misa rows contain no session marker and must remain separate
occurrences (or later children of a primary-source fiesta programme), never a
session family.

## Follow-up source work

The Todo repair is necessary because Todo is already integrated and should not
starve a local event, but Todo remains supplemental.

The first primary-source follow-up is now implemented separately: a bounded
official Turismo WordPress programme adapter discovers current-year
programme-shaped Spanish articles, reuses unchanged article state, reads only
changed/new article text, requires evidence-bound structured facts, and keeps
the existing Campo adapter independent. A live source probe on 26 September
found the Rosario article as candidate ID `123664`, modified
`2026-09-15T14:45:58`.

One independent primary-source improvement remains desirable:

1. **Ayuntamiento programme backstop.** Inspect the lightweight municipal news
   index for new/changed programme posts and process an event-specific official
   poster once when the page is image-only.

That backstop should remain a separate change so its image contract, cost and
failure behavior can be reviewed independently. Facebook image OCR and more
frequent polling are not needed for this incident class.

## Acceptance checks

Before production promotion:

- a Rosario-shaped metadata excerpt `19 Sep–18 Oct` must resolve from detail
  to the explicit 26 September section;
- its 17:00 / 19:50 / 20:00 rows must enter the existing row completeness path;
- a backlog larger than six must still give bounded progress to an unchecked
  local candidate without increasing the six-detail budget;
- incomplete extraction must preserve safe date discovery but not falsely mark
  failed rows processed;
- the current multi-session grouping regressions must stay green;
- ordinary no-date metadata cards must remain excluded from unnecessary detail
  downloads;
- a full repository test run and production-equivalent catalogue preview must
  pass before merge/deploy.
