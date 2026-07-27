# 0004: Phone-first Morning Digest layout

- Status: Accepted
- Date: 2026-07-26

## Context

The digest content is useful but a report-like sequence is slower to scan on a
phone. The product needs one learned visual structure, not additional data or
formatting flexibility.

## Decision

- Use the exact canonical layout in `docs/kb/05_Features.md`.
- Start with `🌅 Доброе утро, Гуардамар!`; never show the word `дайджест`.
- Keep weather, sea, and wind as three compact mandatory rows.
- Append forecast wind speed inline to the current wind row.
- Keep warnings, traffic, and events optional and omit empty sections.
- Never change section order.
- Show no user-facing source footer or explanatory text.
- Keep the complete message within one phone screen.

This ADR supersedes only the separate wind-forecast-line presentation in ADR
0003. It does not change that ADR's source selection or deterministic forecast
rule.

## Consequences

- Users can learn the layout and scan it quickly.
- Missing mandatory values need an explicit `—` rather than invented data.
- The formatter needs a later focused implementation change and tests.
- Sources, normalized data, scheduling, delivery, dependencies, and runtime
  architecture remain unchanged.

## Alternatives considered

- Prose summary: rejected because it is slower to scan.
- Separate current and forecast wind rows: rejected as visually verbose.
- Dynamic section ordering: rejected because predictability is more valuable.
