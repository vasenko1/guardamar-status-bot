# ADR 0019: AEMET representative sea forecast

- Status: Accepted
- Date: 2026-07-28

## Context

The digest needs one compact sea temperature and useful wave context. Averaging
nearby SafeBeach readings would invent a value, while listing a temperature and
sea state for every beach would overload the message. AEMET already publishes
one official forecast for Centro / La Roqueta with water temperature and two
sea-state periods.

## Decision

- Use today's AEMET Centro / La Roqueta water temperature as the representative
  sea temperature.
- Normalize both AEMET `oleaje` descriptions.
- If both periods are equal, render one phrase such as
  `умеренные волны`.
- If they differ, render one compact transition such as
  `слабые → умеренные`, omitting the redundant word `волны`.
- Use active SafeBeach Centre temperature and sea state only when the
  corresponding AEMET value is unavailable.
- Continue to obtain flags and jellyfish only from SafeBeach.

## Consequences

- The sea row stays short and uses one internally consistent official forecast.
- No averaging, additional source, AI call, cache, or background job is added.
- SafeBeach still improves graceful degradation without blocking weather
  delivery.
