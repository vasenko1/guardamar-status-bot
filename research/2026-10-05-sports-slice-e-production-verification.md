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

## First scheduled-run observation — 2026-10-06

The first real automatic Sports Today lifecycle was observed after both cron
windows on production `main=3a918380af5726bf339d6ce221f0810b12eb4499`.

That production revision is a descendant of the reviewed Slice E runtime. Its
post-Slice-E changes cover local clock-change/calendar notices and a bounded
Rosario municipal-source correction; the Sports Today producer, shared planning
loader, Sports Today wrapper and Sports Today cron rows were unchanged.

Observed source freshness for local day 2026-10-06:

- Agenda Guardamar: fresh;
- Municipal agenda: fresh;
- Library: fresh;
- AM Guardamar: fresh;
- FACV: fresh, zero current rows;
- Pesca CV: fresh, two future rows;
- CONVEGA: stale/missing at 08:25/09:25 because its normal refresh runs later,
  at 12:47; it was fresh when inspected after that refresh.

The CONVEGA timing mismatch is not a Slice E failure because CONVEGA does not
currently assign `Event.sport`; the authoritative sport-identity sources FACV
and Pesca CV were both fresh before the Sports Today primary run. If CONVEGA or
another later-refreshing source becomes an authoritative sport source in a
future slice, its refresh timing must be revisited before relying on it for
08:25 current-day publication.

Automatic lifecycle evidence:

- exact 08:25 Sports Today cron row present once;
- exact 09:25 recovery row present once;
- `crond` running;
- 08:25 executed and logged
  `SKIP: no verified current-day sports are eligible`;
- 09:25 executed and logged the same no-event skip;
- no runtime error or traceback;
- no Telegram delivery was attempted;
- `state/sports_today.json` remained absent;
- no uncertain-delivery state existed;
- production worktree remained clean;
- resident `telegrambot listen` service remained running.

This is the expected no-event branch of the reviewed lifecycle: both automatic
runs execute, no resident-facing post is created, and no delivery state is
created merely because the day has no eligible sport.

## Gate result

**PASS — production activation and first scheduled lifecycle**

Sports Slice E is fully production-verified.

Slice F and later sports source/access expansion remain separate work and should
not change the verified Slice E delivery semantics without their own review and
production gate.
