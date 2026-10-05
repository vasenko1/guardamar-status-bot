# Sports Slice B implementation review — 2026-10-05

## Scope

Verification gate for Slice B of ADR 0100:

- append `Event.sport`;
- preserve explicit FACV/Pesca sport identity;
- make global event merge sport-aware;
- add one small deterministic presentation helper;
- change no resident routing, source requests, cron or persistent state.

Base main:
`abee1bcfdd00b57a733f4a802fe9c1f952ef46b2`

## Production prerequisite

Slice A production verification is PASS and recorded in:

`research/2026-10-05-sports-slice-a-production-verification.md`

## Implemented

### Event contract

`sport: Optional[str] = None` is the final Event dataclass field.

Appending rather than inserting preserves every older positional argument
position. Existing Event construction defaults to `sport=None`.

### Existing federation projections

No new HTTP or snapshot schema was introduced.

- FACV's already validated raw `sport="chess"` now survives Event projection.
- Pesca CV's already validated raw `sport="fishing"` now survives Event
  projection.

### Merge contract

Before the existing booking/time/title/place duplicate logic:

- two different non-null sport codes cannot merge;
- same sport continues through existing matching;
- known sport + `None` may merge under the existing identity evidence.

When an allowed merge occurs, the result keeps
`current.sport or event.sport`.

No existing fuzzy threshold, booking identity or place/title rule was changed.

### Presentation helper

`sports_presentation.py` is deterministic, source-free and state-free.

For Slice B it deliberately recognizes only the two actually enabled sport
codes:

- `chess` -> `♟ Шахматы`;
- `fishing` -> `🎣 Спортивная рыбалка`.

Unknown future codes fail explicitly instead of silently inventing labels.
The helper returns presentation text and never mutates the source Event title.

## Tests

Focused verification covers:

- Event sport field is last and optional;
- FACV projection -> chess;
- Pesca projection -> fishing;
- sport + unknown duplicate -> one event retaining sport;
- different known sports with identical title/time/place -> two events;
- same-sport duplicates still merge;
- presentation helper leaves source title unchanged;
- unsupported sport codes fail explicitly;
- existing event contract/merge regressions remain green.

First verification run:

- compileall: PASS;
- focused Slice B suite: **64 tests, OK**;
- full repository suite: **1615 tests, OK**.

## Manual code review

Checked after the first green run:

- no Morning/Tomorrow/Weekend filter or renderer changed;
- no cron/source request/state schema changed;
- the sport guard executes before fuzzy duplicate acceptance;
- booking identity cannot override a known sport conflict;
- a sport learned from a later authoritative duplicate is preserved;
- dataclasses.replace callers preserve the new field automatically unless
  explicitly overridden;
- the presentation helper does not become identity input;
- no speculative football/volleyball/etc. codes were added ahead of their
  accepted source adapters.

No implementation defect was found in this review cycle.

## Final branch-head verification

After the documentation/checkpoint updates, the final application branch head
was verified again:

- compileall: PASS;
- focused Slice B suite: **64 tests, OK**;
- full repository suite: **1615 tests, OK**.

The `ERROR` lines present in the full-suite log are expected negative-path
tests that deliberately simulate Telegram/source failures; the test process
completed `OK`.

## Gate status

**PASS**

No unresolved code, merge, compatibility, source-cost, state, routing or
regression-test objection remains for Slice B.

The temporary branch-only verification workflow is cleanup-only and must be
removed before PR/final diff. Removing it does not alter the tested application
tree.

Slice C must not begin until Slice B is merged, deployed and production-verified.
