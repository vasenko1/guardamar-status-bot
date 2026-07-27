# ADR 0014: Reviewed Guardamar holiday calendar

## Status

Accepted — 2026-07-27

## Context

The municipal market ordinance moves a Wednesday market to the preceding
Tuesday when Wednesday is a holiday. A weekday-only rule would therefore show
the market on the wrong date. Holiday calendars change annually, and silently
guessing a future calendar conflicts with the project's reliability rules.

## Decision

- Keep a small, reviewed in-code calendar of national, Comunitat Valenciana,
  and Guardamar local holidays for each supported year.
- Apply the ordinance deterministically: omit the market on a holiday
  Wednesday and show it on the preceding Tuesday.
- Check the Mayor channel for an explicit exception on the resulting market
  date, whether Tuesday or Wednesday.
- Omit the recurring market when the current year's calendar has not been
  reviewed.
- Add the next official calendar once per year; do not add a dependency,
  runtime calendar API, cache, or background update.

The 2026 calendar is based on BOE-A-2025-21667 and the official 2026 local
holiday publication (DOGV, 14 November 2025). Guardamar's local holidays are
24 July and 7 October.

## Consequences

Holiday moves are correct and cost no network request. Annual review is an
explicit maintenance task. If it is missed, silence is preferred to publishing
the market on an unverified date.
