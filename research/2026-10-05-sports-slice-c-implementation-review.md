# Sports Slice C implementation review — 2026-10-05

## Scope

Verification gate for Sports Slice C:

- preserve the existing strict FPCV base calendar;
- add bounded FEPyC national occurrence authority;
- add bounded FPCV convocatoria/details normalization;
- correct the known 23-29 vs 26-29 national championship conflict;
- enrich fishing Event facts before resident-facing sports activation;
- add no sports publication surface, new cron or Event Access source.

Base main:
`0c01686545ee90236a2ab33a433b6f24a17d789f`

## Prerequisite gates

- Slice B production verification: PASS.
- Slice C live Termux source-contract probe: PASS.
- ADR 0101 / Runtime Constraints documentation gate: PASS.

## Runtime implementation

### Existing base calendar remains unchanged

`state/pesca_cv_events.json` retains its exact existing schema and validator.

The existing `python -m telegrambot.pesca_cv` 05:10 one-shot still refreshes
that calendar first. Slice C then performs best-effort enrichment in the same
process.

### FEPyC authority

New state:

`state/fepyc_fishing_authority.json`

The first accepted authority is the explicit `26MC26` page. It retains:

- stable source ID;
- exact competition name;
- specialty/category/type;
- Guardamar place;
- exact 26-29 November 2026 dates;
- source observation timestamp.

The Event projection joins authority only when:

- base level is national;
- reviewed title identity matches;
- raw FPCV range overlaps the FEPyC occurrence range;
- authority observation is not in the future and is <=36 hours old.

Without current accepted authority, the known-ambiguous national event is
withheld instead of publishing unsafe FPCV dates.

### FPCV convocatoria details

New state:

`state/pesca_cv_details.json`

The annual index is parsed only for current/future base events already accepted
by the Guardamar FPCV calendar.

The source-specific cap is four relevant detail records.

For one eligible row:

- date/scope/modality must deterministically join one base event;
- province must be Alicante;
- venue must prove Guardamar unless the row explicitly says CANCELADO;
- at most one approved official PDF link is accepted.

The reviewed 17 October PDF normalizes:

- provincial Alicante / qualification context;
- two three-hour heats;
- 16:00 concentration;
- 18:00-21:00 first heat;
- 22:30-01:30 second heat;
- Guardamar beach venue;
- club-mediated registration deadline/fee for later Slice G use.

No proactive registration lifecycle is enabled here.

### Same-URL PDF changes

A relevant exact PDF is byte-read on a successful daily details refresh and
SHA-256 checked.

`pdftotext` runs only when either:

- index semantic identity changed; or
- PDF content SHA changed.

This closes the risk that FPCV replaces PDF content at the same URL while
avoiding repeat text extraction for unchanged bytes.

### Freshness

Authority/details may override/enrich a base Event only for 36 hours after
source-backed `observed_at`.

This allows one missed daily refresh but prevents:

- stale FEPyC dates from indefinitely overriding the base calendar;
- stale CANCELADO state from indefinitely hiding a current event;
- stale rich schedule/access facts from being presented as current.

## Verification cycles and defects found

### Cycle 1

Initial focused run did not start because a test bytes literal contained
non-ASCII source text.

Fix: use UTF-8-safe source fixture representation.

This was test-only; runtime was unchanged.

### Cycle 2

Focused and full suites passed.

Manual review found that decorative/service rows in the FPCV annual table could
raise a date-schema error.

Fix: ignore table-shaped rows with no dd/mm/yyyy date while retaining strict
validation for actual dated rows.

### Cycle 3

Focused/full suites passed.

Manual review found that the parser required a PROVINCIA column but did not
verify its value.

Fix: only Alicante rows are eligible for Guardamar details.

### Cycle 4

Focused/full suites passed.

Manual identity review found that a national authority join based only on
level+title could attach a reviewed occurrence to a future same-title event.

Fix: source FPCV range must overlap the FEPyC occurrence range.

### Cycle 5

Focused/full suites passed.

Red-team source review found a substantive stale-content gap: unchanged index
URL/row identity skipped PDF retrieval entirely, so same-URL PDF replacement
would never be detected.

Fix:

- byte-read the relevant exact PDF on each successful daily details refresh;
- store SHA-256;
- skip `pdftotext` only when row identity and PDF bytes are both unchanged.

A follow-up focused test initially failed because one negative-path test had not
been updated for the new content-hash parser parameter. The test was corrected
and the full cycle restarted.

### Cycle 6

Red-team freshness review found that last-good authority/details had no age
gate.

Fix: one common 36-hour projection freshness limit. Old state may remain stored
for diagnostics/recovery, but cannot override/enrich current events after the
limit.

### Cycle 7

Source-quality/load review found two final gaps:

- national Event copy still lost the explicit Campeonato de España / Dúos
  context already available from FEPyC;
- an eight-document detail cap was too generous for a weak Android one-shot.

Fix:

- retain exact competition name in authority state and project
  `Чемпионат Испании · категория дуэты`;
- cap FPCV details at four;
- skip the FPCV index entirely when the accepted base calendar contains no
  current/future events.

Two subsequent focused runs exposed old test fixtures that had not yet carried
the newly required FEPyC competition-name field / UTF-8 fixture shape. Both
were test-only and were corrected before rerunning the full gate.

## Current test result before final documentation run

On the final runtime implementation head before documentation synchronization:

- compileall: PASS;
- focused Slice C suite: **76 tests, OK**;
- full repository suite: **1635 tests, OK**.

Expected ERROR log lines in the full suite are deliberate negative-path
Telegram/source tests; the unittest process completed OK.

## Overengineering review

The source module is intentionally explicit and comparatively large because it
contains two tightly coupled fishing enrichment surfaces plus their exact
validators, bounded state, PDF parser and failure semantics.

A split into generic document/source/state frameworks was rejected:

- it would not remove any source-specific parsing or validation;
- it would add cross-module abstractions before a second implementation needs
  them;
- no dynamic provider registry, generic PDF framework, queue, database or
  scheduler is present.

The implementation remains one narrow fishing-enrichment boundary used only by
the existing Pesca 05:10 one-shot.

If future FEPyC/FPCV sources materially expand beyond this reviewed contract,
module splitting can be reconsidered as a code-organization refactor without
changing the product architecture.

## Invariants rechecked

- old `pesca_cv_events.json` exact schema unchanged;
- old code ignores the two new state files;
- no cron row added;
- no Telegram send added;
- no Event Access source enabled;
- base calendar success is independent from enrichment success;
- index/PDF failure does not delete/corrupt the base calendar;
- national unsafe dates fail closed;
- stale authority/details cannot override the base Event;
- same-URL PDF replacement is detected by content hash;
- PDF text extraction remains under ADR 0101 bounds;
- no browser/OCR/runtime AI/new dependency.

## Gate status

**PASS pending final branch-head compile/focused/full run and temporary
verification-workflow cleanup.**

Slice D remains blocked until Slice C is merged, deployed and
production-verified.
