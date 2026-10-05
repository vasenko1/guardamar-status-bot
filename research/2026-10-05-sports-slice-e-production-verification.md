# Sports Slice E production verification — 2026-10-05

## Production revision

Deployed and verified:

`c1b303b356f33fc28ad2e8154ccbc448b27e236b`

Branch: `main`.

This revision includes the follow-up CLI hotfix from PR #322, so both
`sports-today` and `sports-today-preview` are accepted by the top-level
argparse parser before production activation.

## Verification evidence

The Termux production gate completed successfully:

- production started from clean `main=8ebb57948b07f3f6c11e46fe7880a1bbd5c9fdf9`;
- the only resident process was the expected `telegrambot listen` preview
  listener;
- exact reviewed `origin/main=c1b303b356f33fc28ad2e8154ccbc448b27e236b`
  was fetched and tested in a detached worktree before activation;
- exact-target compileall: PASS;
- focused sports/planning/CLI production suite: **83 tests, OK**;
- no conflicting one-shot lifecycle started during the staging gate;
- `guardamar-preview` was stopped before the fast-forward and restarted after
  activation;
- listener PID changed from `20959` to `30546`, proving the resident
  process reloaded the new Python modules;
- Event compatibility tail is
  `programme_display_title, sport, occurrence_status`;
- the existing event-planning cron installer added exactly one Sports Today
  primary row at **08:25 Europe/Madrid** and one recovery row at **09:25**;
- cron content outside the managed event-planning block remained unchanged;
- `crond` remained running;
- the real top-level command
  `python -m telegrambot sports-today-preview` executed successfully;
- the preview produced no Telegram delivery and
  `state/sports_today.json` remained absent before and after the preview;
- final production branch was `main`, exact HEAD was the reviewed target and
  the production worktree was clean.

The read-only Sports Today preview logged that the Agenda Guardamar snapshot was
stale/missing for local observation day 2026-10-05 and therefore omitted that
single source. The shared planning loader behaved correctly by failing closed,
but a later source-health audit showed that the underlying production snapshot
had been overwritten with an old 2026-09-11 copy after a successful 2026-10-05
05:30 source sync.

The stale file was preserved for forensics, then repaired through the canonical
`sync-agenda-events` lifecycle at 22:21 Europe/Madrid. Repair verification:

- new `fetched_at=2026-10-05T22:21:58.925312+02:00`;
- 12 Agenda Guardamar facts;
- fresh same-day snapshot;
- source log recorded a successful 12-fact sync;
- a subsequent `sports-today-preview` returned no eligible current-day sport;
- `state/sports_today.json` remained absent before and after the preview;
- no Telegram publication occurred;
- production worktree remained clean on
  `c1b303b356f33fc28ad2e8154ccbc448b27e236b`.

The exact writer that restored the stale Agenda snapshot at 19:35 could not be
proven retrospectively. It is tracked separately as an operator/source-state
incident and is not attributed to Slice E runtime code.

## Remaining first-run observation gate

Activation is complete, but the first scheduled daily lifecycle has not yet
been observed because deployment happened after the day's 08:25/09:25 window.

The next operational verification should inspect, without manual delivery:

- same-day freshness of the accepted local event snapshots before 08:25;
- the 08:25 Sports Today wrapper log;
- whether a terminal `sports_today.json` state exists only if Telegram
  delivery was actually attempted;
- the 09:25 recovery behavior;
- absence of duplicate delivery or unexpected source/network work.

A stale or missing optional source alone is not a release failure. A source
freshness pattern that removes the only authoritative sport source for a known
current-day sport, a CLI/wrapper failure, an unexpected state mutation, or a
duplicate recovery send would fail the first-run gate.

## Gate result

**PASS — production activation**

Sports Slice E is active on production.

The remaining observation is an operational first-scheduled-run check, not a
code/deployment blocker. Slice F and later source/access expansion should remain
separate from this observation and should not change Slice E runtime semantics.
