# Sports Slice A implementation review — 2026-10-05

## Scope

Verification gate for Slice A of ADR 0100:

- extract one shared crash-safe dated-publication state primitive;
- preserve Tomorrow state/schema/behavior;
- protect Friday Weekend against ambiguous Telegram delivery duplicates;
- retain the legacy Weekend success marker for rollback compatibility;
- add no sports publication behavior, source requests or cron changes.

Reviewed branch: `feat/sports-foundation-slice-a`

Base main at slice start:
`d63807751fab0c08656748714ec1ab78d3739765`

## Implemented

### Shared dated publication state

Added `src/telegrambot/dated_publication.py` with the exact small
`version/target_date/status/message_id` state shape already used by Tomorrow.

It retains:

- strict validation;
- atomic temporary-file + fsync + replace writes;
- mode 0600;
- non-blocking file lock;
- `uncertain` before non-idempotent send;
- `sent` only after a confirmed positive Telegram message ID.

### Tomorrow compatibility

`TomorrowEventState` is now a thin compatibility wrapper over the shared
primitive.

The production path and `state/tomorrow_events.json` schema are unchanged.
A regression test loads the exact old v1 sent JSON and verifies it remains
readable and clearable without migration.

### Weekend delivery hardening

Weekend now uses:

- legacy `state/weekend.json` as the rollback-compatible successful-target
  marker;
- new `state/weekend_delivery.json` as crash-safe ambiguous-delivery state.

Publication behavior:

1. legacy published marker -> no send;
2. new `sent` -> repair a missing legacy marker, no send;
3. new `uncertain` -> no send/recovery duplicate;
4. reserve `uncertain` before Telegram;
5. retry only explicit Telegram 429;
6. deterministic rejection clears the reservation;
7. timeout/network/5xx ambiguity stays uncertain;
8. confirmed Telegram send writes the legacy marker, then confirms the new
   message ID.

Preview touches neither Weekend state file.

## Verification cycle 1

Initial implementation passed compile and focused/full tests.

Manual code review then found one deployment-boundary defect:

- old runtime serializes Weekend with `state/weekend.json.lock`;
- the first new implementation serialized only with
  `state/weekend_delivery.json.lock`;
- an old process already running during a deploy could therefore overlap a new
  process despite each implementation being internally locked.

### Fix

New Weekend publication acquires **both** the legacy lock and the new delivery
lock.

A regression test holds the legacy lock and verifies the new runtime fails
closed before building/sending.

This fix adds no daemon, retry loop, source request or state migration.

## Verification cycle 2

After the lock fix:

- compile: PASS;
- focused Slice A tests: PASS;
- full suite: PASS.

## Verification cycle 3 — final code/docs state before gate report

GitHub Actions run on the final implementation/docs commit
`18b3248be34fb27140fe5745a3e08da551b23017`:

- compileall: PASS;
- focused command:
  `python -m unittest tests.test_tomorrow_events tests.test_main tests.test_termux_weekend`;
- focused result: **77 tests, OK**;
- full command:
  `python -m unittest discover -s tests`;
- full result: **1608 tests, OK**.

The `ERROR` log lines seen during the full suite are expected assertions from
negative-path tests that deliberately simulate Telegram/source failures; the
test process completed `OK`.

## Manual review checklist

Verified after tests:

- Tomorrow JSON schema is unchanged;
- Tomorrow state path/env name is unchanged;
- Weekend no-message path writes no delivery marker;
- Weekend preview writes neither state file;
- explicit 429 remains the only automatic new-message retry class;
- deterministic unsent Telegram failure clears the Weekend reservation;
- ambiguous Telegram failure keeps `uncertain` and blocks 20:15 recovery;
- legacy successful marker blocks the new runtime;
- new confirmed marker can reconstruct a lost legacy success marker without a
  Telegram send;
- confirmed send + legacy marker write failure leaves new state uncertain;
- legacy marker success + later new-state write failure still blocks duplicates
  through the legacy marker;
- old/new runtime lock overlap is prevented;
- no cron schedule changed;
- no event source or sports content behavior changed;
- no dependency was added.

## Temporary verification workflow

The repository had no general Python CI workflow. A branch-only temporary
GitHub Actions workflow was added solely to execute compile/focused/full tests.

It is not part of the feature architecture and must be deleted from the branch
after the final post-report verification. The tested implementation remains
unchanged when that workflow file is removed.

## Verification cycle 4 — post-report final run

The branch-head verification after adding this gate record also passed:

- compileall: PASS;
- focused suite: **77 tests, OK**;
- full repository suite: **1608 tests, OK**.

No runtime code changed between verification cycle 3 and cycle 4; the intervening
commits updated only this review/checkpoint documentation.

## Gate status

**PASS**

The Slice A implementation itself has no unresolved code, state, delivery,
rollback, runtime-cost or regression-test objection.

The temporary branch-only verification workflow is cleanup-only and must be
removed before PR/final diff. Removing that workflow does not change the tested
application tree.

Slice B may begin only after that cleanup and one final branch diff/main-delta
check.
