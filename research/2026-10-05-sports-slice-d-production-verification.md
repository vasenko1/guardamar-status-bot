# Sports Slice D production verification — 2026-10-05

## Production revision

Deployed and verified:

`d5b83bbf5721db00beb0dd922c028a283540471a`

Branch: `main`.

## Verification evidence

The Termux production gate completed successfully:

- exact reviewed `main` was confirmed and fast-forwarded;
- no affected Tomorrow/Weekend/Pesca/source process was running first;
- compileall: PASS;
- focused Slice D production suite: **146 tests, OK**;
- full repository suite: **1653 tests, OK**;
- read-only Tomorrow production preview: PASS;
- read-only Weekend production preview: PASS;
- the shared local planning loader returned current merged events without
  source HTTP/AI;
- Weekend `include_recurring=True` preserved exactly one
  `Рынок Campo de Guardamar`;
- the same target with `include_recurring=False` did not gain that recurring
  market;
- all state files listed by the verification manifest were byte-identical
  before/after the verification;
- the existing cron rows remained unchanged;
- no Sports Today cron or state existed;
- `guardamar-preview` restarted and remained running;
- no Telegram publication was triggered.

The live previews demonstrated fail-closed freshness behavior for the path they
were explicitly given by the operator smoke test. A later audit found that the
production verification used the wrong Agenda Guardamar path in both the state
manifest and the direct-loader smoke: `state/agenda.json` instead of the actual
runtime default `state/agenda_guardamar.json`.

## Post-verification correction — Agenda Guardamar path

This is a defect in the operator production-gate script, not in Slice D runtime
code.

Consequences:

- the "all monitored production state files were byte-identical" statement did
  not include the real Agenda Guardamar snapshot;
- the direct-loader smoke intentionally omitted an absent `state/agenda.json`
  and therefore did not exercise the live Agenda Guardamar snapshot;
- the core Slice D code/tests, Tomorrow/Weekend previews, recurring rules and
  fail-closed loader behavior remain valid, but the Agenda-state immutability
  sub-gate was incomplete.

A later production audit on 2026-10-05 found the real
`state/agenda_guardamar.json` with `fetched_at=2026-09-11T10:10:00+02:00`
despite successful daily Agenda sync log entries through 2026-10-05. Its file
mtime was 2026-10-05 19:35:03 Europe/Madrid, proving that the live snapshot had
been overwritten after the successful 05:30 sync. The exact local writer could
not be established retrospectively.

The investigated direct Agenda writer tests use temporary directories, and no
reviewed deployment/verification script was found to copy, move or restore
`state/agenda_guardamar.json`. Therefore the overwrite cause is recorded as
**unknown local overwrite** rather than attributed to the full test suite.

Operational correction:

- preserve the stale snapshot as forensic evidence;
- refresh only through the canonical `sync-agenda-events` source lifecycle;
- future production tests run off the production path;
- production state manifests must resolve the same runtime path/defaults used
  by the application instead of duplicating guessed filenames.

## Gate result

**PASS**

Slice D is complete in production.

Slice E may proceed. Slice F and later source/access work remain blocked until
Slice E passes its own implementation, review, merge and production gates.
