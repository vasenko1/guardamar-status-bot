# 0003: Compact wind forecast

- Status: Accepted
- Date: 2026-07-26

The separate forecast-line presentation below is superseded by the inline
phone layout in ADR 0004. The source and deterministic selection rule remain
accepted.

## Context

Current wind alone does not show whether conditions will strengthen or weaken
later. AEMET already supplies Guardamar forecast wind, so the digest can add
this value without another source or architectural change.

## Decision

- Keep current wind as one compact row.
- Append at most one later-day forecast speed to that row.
- Select the strongest valid forecast period remaining before local midnight.
- Show `→` and forecast speed after current direction and speed.
- Prefer the active Platja Centre SafeBeach wind as the current beach value.
  Otherwise use the available AEMET wind value. Render both current and
  forecast speed in metres per second.
- Omit the inline continuation unless current wind and a comparable AEMET
  daily forecast are both available or both speeds are equal.
- Keep the canonical section order defined in `docs/kb/05_Features.md`.
- Do not show source labels in the user-facing digest.

## Consequences

- Wind evolution is visible without creating a weather report.
- Output remains deterministic and within one mobile screen.
- The normalized weather record and formatter need a small later
  implementation change and focused tests.
- Collection, scheduling, delivery, dependencies, and approved sources remain
  unchanged.

## Alternatives considered

- Multiple hourly periods: rejected as too verbose.
- A separate wind section: rejected as unnecessary structure.
- A new forecast provider: rejected because AEMET already supplies the data.
