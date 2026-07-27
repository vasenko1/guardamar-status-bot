# ADR 0013: Dynamic weather icon

## Status

Accepted

## Context

The fixed `🌤` icon does not reflect the official AEMET sky forecast. The
weather row already represents the whole day, so its icon should communicate
the most relevant forecast condition without adding text or another source.

## Decision

- Normalize AEMET `estadoCielo.descripcion` values into a small fixed set:
  clear, partly cloudy, cloudy, fog, rain, snow, and storm.
- Render them respectively as `☀️`, `🌤`, `☁️`, `🌫️`, `🌧️`, `🌨️`, and
  `⛈️`.
- When AEMET supplies several periods, select the most significant condition
  using this order: storm, snow, rain, fog, cloudy, partly cloudy, clear.
- Use neutral `🌤` when no known condition is available.
- Keep the rest of the weather row and section order unchanged.
- Use no AI and no source other than the existing AEMET daily forecast.

## Consequences

The row remains the same length while conveying more useful daily context.
The icon represents the most significant forecast period, not necessarily the
condition at the exact moment the digest is sent.

## Alternatives rejected

- Current observation icon: AEMET observation data used by the bot has no
  equivalent compact sky-condition field.
- Multiple icons by hour: too verbose for the phone-first digest.
- AI classification: unnecessary for AEMET's controlled descriptions.
