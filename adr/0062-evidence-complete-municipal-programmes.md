# ADR 0062: Evidence-complete municipal event programmes

Date: 2026-09-12

## Status

Accepted.

## Context

The 11 September weekend publication for 12–13 September omitted real
municipal activities and the Fiestas del Campo finale. A duplicated, long
Todo Cultura reproduction could return a nonempty but partial model result;
the date cursor then made the omission durable. The monthly municipal MUPI
contained a too-small inset of the festival's complete programme. A library
exhibition date range also produced false weekend access despite closed hours.

## Decision

- Keep one normalized event catalog shared by morning and weekend selectors.
- Before advancing a Todo programme date, account for every independent timed
  row. Recover missing small rows individually; use a strict deterministic
  parser only for quoted activities with explicit date, time and venue. Retain
  prior facts and do not advance the cursor on incomplete extraction.
- Persist explicitly named future same-weekday repeats from a verified row,
  validating the stated month and actual weekday, even beyond the seven-day
  polling window and even if another row's model extraction fails.
- Add a bounded, credential-free public Turismo WordPress article/poster read
  for the Campo festival. Prefer explicit dated article facts to conflicting
  combined vision candidates. Keep fireworks and chocolate untimed when the
  primary publication supplies no exact time. Poster/model failure cannot
  erase the complete article-stated programme.
- Use official library opening weekdays to filter exhibition ranges. Preserve
  old snapshots safely until a new hours read succeeds.
- Treat primary-source changes/cancellations as updates; lack of an item in a
  supplemental feed alone is never cancellation.

## Consequences

There is no new dependency, raw source cache, general event platform or
additional morning fetch. A municipal sync may perform more bounded model
calls when a programme is incomplete, but it now fails closed instead of
publishing a partial catalogue as complete. Article-specific extraction is
deliberately narrow and evidence-bound; other festivals require their own
source audit before extension. Operational verification must compare the
published output with an independently collected calendar, not merely the
poster examples supplied by a user.
