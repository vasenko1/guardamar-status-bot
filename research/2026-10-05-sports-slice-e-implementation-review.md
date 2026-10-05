# Sports Slice E implementation review — 2026-10-05

## Scope status

Slice D is production-verified.

Slice E is the first resident-facing sports publication slice. The code portion
implemented so far covers E1-E5 and E7. Exact E6 cron minutes are deliberately
not committed until live Termux duration evidence is reviewed.

The work was rebased onto current main
`8ebb57948b07f3f6c11e46fe7880a1bbd5c9fdf9`, which concurrently added the
verified next-day municipal market alert in PR #320. The sports changes were
reapplied semantically so the market contract remains intact.

## Implemented

### Tomorrow

- preserves the PR #320 verified market merge/check;
- after that merge, separates sport/non-sport presentation;
- renders sport under `🏅 Спортивные мероприятия`;
- keeps Friday/Saturday suppression;
- cancelled occurrences are not turned back into proactive plans;
- image eligibility is calculated from final presentation units;
- mixed source programmes render the parent only once.

### Weekend

- keeps existing Friday local snapshot lifecycle and crash-safe delivery;
- inside each day, ordinary events remain under the day heading;
- sport receives a separate sports subsection;
- mixed programme parents are not duplicated;
- whole-weekend optional-teaser compaction from Slice D is preserved.

### Sports Today

- new local-only builder/preview/runtime command;
- reads only accepted fresh local snapshots through the shared Slice D loader;
- zero source HTTP and zero AI in the send path;
- uses one dated crash-safe state `state/sports_today.json`;
- no qualifying sport means no message and no state marker;
- recovery checks sent/uncertain state before rebuilding the publication and
  again under the delivery lock;
- ambiguous Telegram delivery remains uncertain and is not retried
  automatically;
- current-day wording is time-aware but conservative:
  - future: `Начало в HH:MM`;
  - started with known end:
    `Началось в HH:MM · окончание в HH:MM`;
  - started with unknown end: `Сегодня с HH:MM`;
  - known ended occurrence is omitted;
  - date-only current occurrence remains eligible.

### Morning

- final Slice E code filters `sport is not None` from Morning after merge.
- This must be deployed atomically with the Sports Today cron; it must not be
  deployed independently while E6 remains unresolved.

### Explicit cancellation

A minimal `Event.occurrence_status` fact is added before the final `sport`
field. The only currently emitted value is source-proven `cancelled` from a
fresh matching FPCV detail.

FPCV cancellation no longer silently disappears from the normalized current-day
event stream. Proactive Tomorrow/Weekend suppress the cancelled occurrence;
Sports Today renders an explicit cancellation correction and removes stale
ticket/registration/teaser presentation.

No generic status state machine is introduced.

The cancellation contract stays deliberately fail-closed: if a cancellation
row can no longer be deterministically joined to the known Guardamar base
occurrence, the bot does not infer locality or reconstruct deleted history.

## Concurrency/main rebase

During the first Slice E implementation pass, main advanced from Slice D
`d5b83bb...` to `8ebb579...` with PR #320.

Because that PR touched Tomorrow and `__main__`, the original Slice E branch
was not merged or force-rebased blindly. A fresh branch was created from
`8ebb579...`; non-overlapping changes were copied, and Tomorrow/runtime
integration was reapplied to preserve the market-alert semantics and tests.

## Verification cycles

### Pre-rebase implementation pass

On the old Slice D base:

- compileall: PASS;
- focused: **205 tests, OK**;
- full: **1673 tests, OK**.

This run is historical only and is not used as the final gate because main
subsequently moved.

### Rebased cycle 1

On current main including PR #320:

- compileall: PASS;
- focused: **251 tests, OK**;
- full: **1687 tests, OK**.

Manual review then found one efficiency/recovery gap: Sports Today built the
local publication before checking an already sent/uncertain dated state. It
could not duplicate a send, but recovery unnecessarily reread snapshots.

The runtime was aligned with the improved Tomorrow pattern: state is checked
before build, then checked again under lock before send. Tests prove both sent
and uncertain recovery skip the builder.

### Rebased cycle 2

After the early-state fix:

- compileall: PASS;
- focused: **251 tests, OK**;
- full: **1687 tests, OK**.

Manual semantic review then changed `Идёт сейчас · до ...` to the more
source-faithful `Началось в ... · окончание в ...`, avoiding an unsupported
claim of continuous activity during competitions with breaks.

### Rebased cycle 3

After conservative started-event wording:

- compileall: PASS;
- focused: **251 tests, OK**;
- full: **1687 tests, OK**.

No unresolved code-level objection remains for E1-E5/E7 at this checkpoint.

## E6 schedule gate — still open by design

The accepted implementation plan forbids hardcoding the previously discussed
08:25 / 09:25 candidate slots before checking live production schedule and
recent duration evidence.

Known current neighboring rows are:

- SUMA 08:05;
- transport notices 08:42;
- guide sync 09:02;
- course notifications 09:42 and 11:42.

The exact Sports Today primary/recovery minutes remain uncommitted until recent
Termux logs for these jobs are reviewed. No sports cron row has been added yet.

## Gate status

**E1-E5/E7 code: PASS**

**E6 schedule: PENDING live read-only duration evidence**

No merge or production deployment is allowed until E6 is resolved, the cron
installer/tests are patched, the complete branch is reviewed again, and
focused/full tests pass on the final branch head.
