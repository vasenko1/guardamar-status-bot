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
- Ignore periods that have ended, collapse adjacent duplicates, and retain at
  most the first and last distinct remaining conditions. Use the matching icon
  for one state and `🌤` for a transition.
- Use neutral `🌤` when no known condition is available.
- Combine the temperature range and compact state transition in the `Небо`
  row defined by ADR 0004.
- Use no AI and no source other than the existing AEMET daily forecast.

## Consequences

The row conveys the expected remaining evolution without becoming an hourly
forecast.

## Alternatives rejected

- Current observation icon: AEMET observation data used by the bot has no
  equivalent compact sky-condition field.
- Multiple icons by hour: too verbose for the phone-first digest.
- AI classification: unnecessary for AEMET's controlled descriptions.
