# Sports Slice D implementation review — 2026-10-05

## Scope

Slice D is infrastructure-only preparation for the later sports publication
activation:

- one shared local planning-event loader for Tomorrow/Weekend/future Sports Today;
- one complete event-section renderer that cannot silently lose a tail;
- essential competition context remains outside optional teaser prose;
- labelled race-distance facts remain distinct.

Base main:
`9816a58558e739337ec043624421a8aabaa51a4c`.

Prerequisite: Slice C production verification is PASS.

## D1 — shared local planning read

`src/telegrambot/planning_events.py` now owns the explicit local read/merge
needed by planning surfaces.

It preserves the existing source order:

1. optional recurring facts;
2. municipal agenda;
3. Agenda Guardamar;
4. Municipal Library;
5. AM Guardamar;
6. FACV;
7. Pesca CV;
8. CONVEGA.

The helper:

- performs no source HTTP and no AI;
- uses each source's existing local reader;
- requires the requested base snapshot observation day for proactive/current
  planning claims;
- preserves source-specific timestamp fields;
- preserves `_prefer_agenda_guardamar_venues` and `_merge_events`;
- passes the same explicit FEPyC authority and Pesca-details state paths into
  the Pesca adapter;
- leaves FEPyC/details 36-hour supplemental freshness to the Pesca adapter;
- supports recurring events only through the explicit
  `include_recurring=True` Weekend call;
- keeps preview diagnostics without admitting stale events into the merge.

Tomorrow now uses this loader with no recurring facts and requires the current
local observation day.

Weekend uses the same loader with recurring facts and requires the Friday/local
run observation day. The Friday 19:15 primary and 20:15 recovery therefore read
the same accepted Friday snapshots rather than promoting an older last-good
catalogue.

No generic source registry/plugin framework was added.

## D2 — complete planning rendering

The legacy `build_event_section()` contract remains truncating for unrelated
existing callers such as Morning.

A new `build_complete_event_section()` reuses the same event/programme/session
block rendering but:

1. attempts every logical event block;
2. on overflow removes only optional `teaser` prose and retries;
3. preserves identity, details, time, schedule and place;
4. raises instead of silently dropping a block if essential content still
   exceeds the planning limit.

Tomorrow now uses this complete renderer.

Weekend renders the whole two-day aggregate from one already-loaded day set. If
the aggregate overflows, it retries both days with optional teasers removed.
It does not refetch any source during that fallback.

No pagination or multi-message transaction was added.

## D3 — essential context

Slice D does not introduce a competition schema. Existing source-backed
competition/division/group/round/stage facts remain in title/details, which are
preserved by compact rendering. Teaser remains optional prose only.

## D4 — multi-distance safety

Regression coverage proves labelled facts such as:

- `Полумарафон: 21,097 км · ...`;
- `10K: 10,5 км · ...`

remain separate because they do not match the generic bare-distance
normalization contract.

The generic route-distance normalization itself was not changed.

## Verification cycles

### Cycle 1

First focused run exposed two test-fixture issues:

- a September Weekend test wrote a municipal snapshot with an August observation
  timestamp, which the newly required freshness gate correctly rejected;
- the initial overflow fixture relied on huge titles, but the established
  renderer intentionally bounds titles to 120 characters.

Fixes were test-only: make the Weekend fixture fresh for its actual run date and
put the oversized essential payload in details.

### Cycle 2

Result:

- focused: **143 tests, OK**;
- full: **1650 tests, OK**.

Manual review then found a real aggregate-rendering defect: Saturday optional
teaser prose could consume enough budget for Sunday to fail even though the
whole Weekend message would fit if optional prose were removed from both days.

### Cycle 3

Fixed Weekend aggregate fallback to:

- load each day once;
- try the full aggregate;
- if needed, remove teasers across both days and rerender;
- never silently lose either day.

Regression confirms both events/context survive and source loading stays one
call per day.

Result:

- focused: **144 tests, OK**;
- full: **1651 tests, OK**.

### Cycle 4

Added a cross-source regression proving the shared loader preserves existing
merge/enrichment semantics, not merely source membership.

Result:

- focused: **145 tests, OK**;
- full: **1652 tests, OK**.

### Cycle 5/6

Added a Tomorrow wiring regression proving an essential aggregate overflow
fails closed rather than dropping a tail. The first run failed because the new
test omitted the `Event` import; runtime code was unchanged.

After correcting that test-only import:

- compileall: PASS;
- focused: **146 tests, OK**;
- full: **1653 tests, OK**.

Expected ERROR lines in the full suite remain deliberate negative-path tests.

## Invariants rechecked

- no sports subsection is enabled;
- no Sports Today command/publication/state exists yet;
- Morning does not exclude sports yet;
- no cron row changed;
- no Telegram delivery lifecycle changed;
- no source HTTP/AI was added to planning send paths;
- source merge order and venue preference are preserved;
- Weekend recurring market behavior remains;
- Tomorrow does not gain recurring events;
- old `build_event_section()` truncation remains for unrelated callers;
- Tomorrow/Weekend cannot silently truncate planning tails;
- no pagination, database, queue, daemon or generic provider framework was
  introduced.

## Gate status

**PASS pending final documentation branch-head compile/focused/full run and
temporary verification-workflow cleanup.**

Slice E remains blocked until Slice D is merged, deployed and production
verified.
