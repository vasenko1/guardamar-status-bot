# ADR 0101: Bounded FPCV convocatoria enrichment for fishing events

- Status: Accepted
- Date: 2026-10-05
- Implementation: Complete in Sports Slice C; production verification pending
- Refines: ADR 0100
- Research: `research/2026-10-05-sports-slice-c-source-contract-recon.md`

## Context

ADR 0100 requires sports events to preserve source-backed competition context
before resident-facing activation. The existing Federación de Pesca CV
calendar supplies dates, level, modality and Guardamar location, but not enough
context for a useful resident card.

A reviewed FPCV convocatoria for the 17 October 2026 Guardamar competition
supplies exactly the missing facts:

- provincial Alicante championship;
- qualification context for Comunidad Valenciana 2027;
- club-mediated registration deadline;
- two three-hour heats;
- exact programme;
- explicit competition venue.

The same official convocatoria index also exposes explicit `CANCELADO`
status rows.

The exact convocatoria is a text-layer PDF. Termux production already has
Poppler/`pdftotext` for separately approved workflows, but current runtime
policy does not authorize generic PDF extraction for sport.

The 2026-10-05 read-only production probe measured:

- FPCV convocatoria index: 161,072 bytes, 2.465 s;
- exact convocatoria PDF: 609,280 bytes, 1.474 s;
- extracted text: 8,442 bytes;
- `pdftotext -layout`: 0.088 s;
- no source/state/cron mutation.

FEPyC independently proves that the national Mar-costa Dúos championship in
Guardamar runs 26-29 November 2026, while the current FPCV operational table
collapses rows into 23-29. Sports publication therefore also needs one narrow
FEPyC national-date authority input before fishing events are emitted.

## Decision

### Keep one fishing preparation lifecycle

Extend the existing short-lived 05:10 fishing preparation path. Do not add a
new cron, daemon or event-access fetch path.

The same sequential source process may prepare:

1. the existing FPCV competition calendar;
2. one small FEPyC national-authority snapshot;
3. one small FPCV convocatoria/details snapshot.

The strict existing `state/pesca_cv_events.json` schema remains unchanged for
rollback compatibility.

### FEPyC national date authority

For reviewed national Guardamar competitions, a bounded first-party FEPyC event
page may supply:

- stable competition ID;
- specialty/category/type;
- Guardamar location;
- exact start/end dates;
- responsible territorial federation.

This authority is consumed inside the fishing projection before generic Event
merge. It is not emitted as a second parallel Event.

For the reviewed conflict, FEPyC owns the national championship occurrence
dates; FPCV remains authoritative for explicit local/regional organization and
access facts.

If FEPyC authority cannot be refreshed and no valid last-good authority exists,
ambiguous FPCV national ranges must be withheld from sports projection rather
than published with known-unsafe dates.

### FPCV convocatoria index

Use only the official annual convocatoria index under
`federacionpescacv.com`.

The adapter may retain only bounded current/future Guardamar competition rows
with deterministic official convocatoria links and explicit cancellation
status.

No generic site crawl is allowed.

### Exact PDF policy

An FPCV PDF is eligible only when:

- the exact URL was obtained from an accepted relevant Guardamar row in the
  official convocatoria index;
- HTTPS host remains `federacionpescacv.com`;
- content type is `application/pdf`;
- payload begins with `%PDF-`;
- response is at most 1 MiB;
- one extraction attempt uses existing Termux `pdftotext -layout`;
- extraction timeout is at most 10 seconds;
- extracted UTF-8 text is non-empty and at most 64 KiB.

No OCR, image rendering, browser, JavaScript runtime or new Python dependency is
allowed.

Raw PDF bytes and extracted text are process-local and discarded after
normalization.

### Request bounds

One 05:10 fishing preparation run may make at most:

- one existing FPCV competition-calendar request;
- one FEPyC authority request for each explicitly retained relevant national
  competition, bounded by the normalized event set;
- one FPCV convocatoria-index request;
- one bounded PDF byte-read for each relevant Guardamar convocatoria on a
  successful daily details refresh, capped at **four** relevant detail records;
- `pdftotext` only when the exact index identity or PDF SHA-256 differs from
  the accepted normalized record.

The current FEPyC authority set is explicit and contains one reviewed event
(`26MC26`), with a structural maximum of four authority records. The FPCV
details set has a structural maximum of four relevant records. The adapter must
not devolve into N-per-team/category polling.

### Separate rollback-safe normalized state

Do not add optional keys to `state/pesca_cv_events.json`, whose validator
requires an exact schema.

Persist new facts separately:

- one bounded FEPyC authority snapshot;
- one bounded FPCV details snapshot.

Old production code ignores these files, so rollback remains possible.

A details/PDF failure must not invalidate or delete a successfully refreshed
base fishing calendar.

### Event projection

The fishing Event projection may enrich the existing event only through
deterministic source-specific joins.

For the reviewed 17 October event, accepted details may express resident facts
such as:

- `Провинциальный чемпионат Аликанте · отбор на Comunidad Valenciana 2027`;
- `2 тура по 3 часа`;
- exact schedule.

Club-mediated registration facts may be normalized now but proactive lifecycle
publication remains deferred to Sports Slice G.

### Failure semantics

- Base FPCV calendar success is independent of details enrichment success.
- Valid last-good authority/details may be retained, but they are eligible to
  override/enrich the base Event for at most **36 hours** after their
  source-backed `observed_at`; future timestamps are ineligible.
- One missed daily refresh may therefore reuse last-good enrichment when the
  same reviewed document cannot be fetched, while a second prolonged outage
  causes national authority to fail closed and ordinary events to drop stale
  detail/cancellation overrides.
- If the index identity changes, or the same URL returns changed PDF bytes, the
  previous semantic detail is immediately ineligible unless the changed
  document parses and validates successfully. The 36-hour allowance never
  authorizes a known-superseded document.
- Stale or mismatched authority/details never override the current base event.
- Known ambiguous national FPCV dates fail closed when authoritative FEPyC
  occurrence evidence is unavailable.
- No source failure triggers Telegram publication from this preparation stage.

## Consequences

### Benefits

- fishing is date-correct before sports publication is enabled;
- the first sports release contains useful competition context rather than raw
  federation modality names;
- one normalized source observation can later feed Event Access without a
  second PDF parser/fetch path;
- rollback of the existing calendar reader remains safe;
- measured Termux cost stays small.

### Costs

- two small normalized source-state files;
- one bounded index parse and changed-document text extraction path;
- source-specific authority/join logic for the known national conflict.

## Alternatives rejected

### Parse the PDF inside Event Access later

Rejected. It would duplicate source work and make the first sports publication
editorially incomplete.

### Add convocatoria fields to `pesca_cv_events.json`

Rejected. Old production code validates the exact existing event keys and would
reject the modified file after rollback.

### Use FPCV 23-29 as the national competition range

Rejected. The responsible national federation explicitly publishes 26-29.

### Generic PDF or sports-document framework

Rejected. The measured need is one bounded FPCV text-PDF contract; broad
abstraction would add complexity without another implemented use.


## Implementation checkpoint

Sports Slice C implements this ADR inside the existing
`python -m telegrambot.pesca_cv` one-shot.

Implemented source artifacts:

- `state/fepyc_fishing_authority.json`;
- `state/pesca_cv_details.json`.

The existing `state/pesca_cv_events.json` schema is unchanged.

The accepted 2026 national authority record preserves the exact FEPyC
competition name, category and 26-29 November dates. The Event projection
renders the source-backed context as
`Чемпионат Испании · категория дуэты`.

The reviewed 17 October FPCV convocatoria normalizes:

- provincial Alicante / qualification context;
- two three-hour heats;
- 16:00 concentration;
- 18:00-21:00 and 22:30-01:30 competition windows;
- source-backed beach venue;
- club-mediated registration deadline/fee for later Event Access use.

Daily FPCV PDF bytes are SHA-256 checked because the publisher may replace a
document at the same URL. Text extraction is skipped when both the index
identity and PDF content hash are unchanged.

Implementation review discovered and corrected:

- non-date service rows in the annual index;
- province validation;
- authority joins without date-overlap evidence;
- stale last-good authority/cancellation overrides;
- same-URL changed PDF content;
- an overly generous eight-document upper bound.

The final source-specific bounds are intentionally small and no generic
document framework, new cron, daemon or Event Access fetch path was introduced.
