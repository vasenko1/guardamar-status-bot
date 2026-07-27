# ADR 0006: AEMET beach-temperature fallback

- Status: Accepted
- Date: 2026-07-27

## Context

SafeBeach publishes an operational flag and water temperature only while its
beach record is active. The morning digest may run before lifeguard service,
leaving the mandatory sea row empty. AEMET already provides an official beach
forecast for Centro / La Roqueta.

## Decision

- Read SafeBeach only for `Platja Centre / Babilònia`.
- Prefer its water temperature when the record is active and the value is
  valid.
- Otherwise use today's forecast water temperature from AEMET beach product
  `0307605`, Centro / La Roqueta.
- Keep the forecast value distinct in the normalized model.
- Obtain the beach flag only from the active SafeBeach record.
- Never infer a flag from AEMET wind, waves, warnings, or temperature.
- Treat either source as optional for the sea row.

## Consequences

- The sea row can show a useful official temperature before SafeBeach becomes
  active.
- The displayed temperature may be a forecast rather than a live beach-service
  value, but the compact user-facing layout does not add a source label.
- One additional small, sequential AEMET product request is made per digest
  build.
- Source failures still degrade to `—` without blocking weather delivery.
