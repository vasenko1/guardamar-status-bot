# Sports Slice E implementation review — 2026-10-05

## Scope status

Slice D is production-verified.

Slice E is the first resident-facing sports publication slice. E1-E7 are now
implemented. E6 cron minutes were committed only after the required live
Termux schedule/duration read confirmed safe staggering.

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

### Rebased cycle 4 — cron + compatibility hardening

After the live E6 gate, the existing planning cron installer gained 08:25 and
09:25 Sports Today rows and its focused Termux regression coverage. That head
passed:

- focused: **262 tests, OK**;
- full: **1688 tests, OK**.

A subsequent red-team review found one compatibility gap that green behavior
tests had not exposed. Slice B had appended `Event.sport` specifically to
preserve existing positional construction, but the initial E7 patch inserted
`occurrence_status` immediately before it. Any caller using the already
introduced positional sport slot could therefore be silently reinterpreted as
a status.

The fix keeps `sport` on its established slot and appends the new
`occurrence_status` field after it. All current status emission remains
keyword-based, so runtime semantics are unchanged. The field-order regression
now protects the compatibility property rather than requiring `sport` to stay
the final field forever.

After this fix:

- compileall: PASS;
- focused: **261 tests, OK**;
- full: **1687 tests, OK**.

The one-test count reduction is intentional: two overlapping field-order tests
were replaced by one compatibility-focused invariant.

## E6 schedule gate — resolved from live production evidence

The accepted implementation plan forbade hardcoding the previously discussed
08:25 / 09:25 candidate slots before checking live production schedule and
recent duration evidence. The production read was performed on clean
`main=8ebb57948b07f3f6c11e46fe7880a1bbd5c9fdf9` before Slice E activation.

Observed neighboring jobs:

- SUMA starts 08:05 and recent completion log lines are around 08:05:02-03;
- transport notices start 08:42 and recent completion lines are around
  08:42:01;
- guide sync starts 09:02 and recent runs completed between about 09:06:31 and
  09:07:40;
- course notifications start 09:42 and 11:42 and complete around the scheduled
  minute;
- resident news starts 11:11;
- the full crontab also retains its established hourly lightweight monitors,
  but neither selected Sports Today minute is an exact start-time collision.

The chosen schedule is therefore:

- primary: **08:25 Europe/Madrid**;
- recovery: **09:25 Europe/Madrid**.

08:25 is 20 minutes after SUMA and 17 minutes before transport. 09:25 is at
least 17 minutes after the observed guide-sync completion range and 17 minutes
before the 09:42 course run. Sports Today itself performs no source HTTP or AI;
it reads bounded local snapshots and only the Telegram send is outbound.

Both rows are added to the existing event-planning/weekend managed cron block.
No new installer, daemon, scheduler or per-sport cron block is introduced.
Installer tests verify one primary row, one recovery row, Europe/Madrid and
idempotent preservation of unrelated jobs.

## Post-merge pre-production CLI gate

The Slice E squash merge itself was not deployed immediately. During the
post-merge production-script review, the actual wrapper-to-CLI path exposed one
release blocker that the earlier unit-level command tests had not covered:
`_run_command()` supported `sports-today` and `sports-today-preview`, but
the top-level argparse `choices` did not.

Therefore `termux/run-sports-today.sh` would have failed at argument parsing
before reaching the reviewed handler. Production was still on the pre-Slice-E
main at discovery time, so no resident-facing omission or duplicate occurred.

The minimal hotfix:

- adds `sports-today` and `sports-today-preview` to the existing CLI choices;
- adds a regression that invokes `main()` through argparse for both commands
  and proves dispatch to `_run_command`;
- changes no sports semantics, source access, state shape, schedule or
  architecture.

Hotfix verification before merge:

- focused CLI/sports/Termux suite: **75 tests, OK**;
- full suite: **1688 tests, OK**.

This is also a deployment-gate lesson for this slice: the production check must
exercise `python -m telegrambot sports-today-preview`, not only call internal
builders or `_run_command` directly.

## Gate status

**E1-E7 implementation: PASS**

**E6 live scheduling gate: PASS — 08:25 primary / 09:25 recovery**

**Architecture / overengineering review: PASS** — the rollout reuses the Event
model, shared planning loader, dated-delivery primitive and existing managed
cron block. No second sports subsystem, source lifecycle, scheduler, daemon,
queue, database or generic status framework was added.

**Gap/risk review: PASS after two pre-production fixes** — the Event positional
compatibility gap was corrected before the Slice E merge, and the missing
top-level Sports Today CLI choices were caught after merge but before any
production activation and fixed in the follow-up hotfix.

Merge remains blocked only until the documentation head receives the same
focused/full CI verification and the temporary branch-only workflow is removed.
