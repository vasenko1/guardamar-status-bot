# ADR 0020: High-probability rain row

- Status: Accepted
- Date: 2026-07-28

## Context

A daily rain line would add routine noise, but a high probability can affect
plans. The existing AEMET municipality response already contains probability
and period data, so no source or request is needed.

## Decision

- Consider forecast periods that have not ended at collection time.
- Prefer periods beginning later in the day; use a currently spanning period
  only when no future period is available.
- Select the highest valid probability.
- Render `🌧 Дождь: <вероятность>% • <период>` only at 75% or above.
- Omit the row for lower, missing, or malformed values.

## Consequences

- High-confidence rain becomes visible without a permanent weather report.
- The implementation adds two optional scalar fields and no dependency,
  request, cache, AI call, or background work.
