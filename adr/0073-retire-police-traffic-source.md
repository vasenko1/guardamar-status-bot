# ADR 0073: Retire Policía Local traffic runtime source

## Status

Accepted — 2026-09-21

## Context

The Policía Local Guardamar traffic page was integrated as an optional Morning
Digest source and later gained a tightly validated Gemini fallback for unknown
HTML notices. In production the source did not behave as a current road-closure
feed. The only useful deterministic case remained one reviewed festival
document; later real traffic changes were not published there reliably.

Keeping the source active therefore imposed one daily network path, traffic-only
models/rendering and an AI fallback without providing dependable resident value.

## Decision

Retire the Policía Local traffic integration from runtime.

- The Morning Digest performs no Policía Local request.
- Remove the traffic task, normalized traffic models and `🚧 Движение` digest
  rendering.
- Remove the traffic-specific Gemini schema/prompt and the Policía adapter.
- Keep historical research and superseded ADRs only as evidence for why the
  source is not an approved runtime feed.
- Reconsider the source only if a stable, current, official machine-readable
  publication path is demonstrated.

This decision does not remove transport schedule/fare notifications, Mayor
channel event/bathing rules, AEMET warnings, or CCE/112 operational monitoring.

## Consequences

The 07:30 path becomes cheaper and simpler, loses an unproductive daily request
and cannot spend model quota on a traffic page that is not maintained as a
live feed. A one-off future road closure published only on that retired page may
be missed; that is an accepted limitation until a reliable source exists.

No replacement traffic scraper, browser automation, social-media polling or
generic municipal-news collector is added.
