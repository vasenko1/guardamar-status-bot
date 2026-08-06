# ADR 0032: Complete Guardamar beach flag coverage

- Status: Accepted
- Date: 2026-08-07
- Supersedes: the three-beach selection rules in ADR 0018 and ADR 0024, and
  the early three-preferred-beach completeness rule in ADR 0021

## Context

The three preferred central beaches often have the same flag. Showing only
those records can hide a stricter flag or jellyfish report at another active
Guardamar beach and make a partial view look representative of the whole
coast. SafeBeach already exposes six named Guardamar zones, so retaining all
verified records adds no request or dependency.

## Decision

- Retain every active, non-ended, timestamped current record for the six known
  zones: Centre / Babilònia, Roqueta, Vivers, Montcaio, Camp, and Ortigues.
- Before 10:40, replace the morning message only when all six zones have valid
  current flags. At 10:40, any non-empty valid subset remains publishable.
- Group flags in red, yellow, green order and keep the fixed beach order within
  each color. Render at most three beach names on one semantic row; allow
  Telegram to wrap text naturally without estimating visual width.
- Render every verified red, yellow, and green beach. Never use a count-only
  suffix or infer a missing beach's color.
- Render `На всех пляжах` only when the exact six-zone set is current and
  green, and no active municipal notice prohibits bathing. Otherwise list the
  verified names.
- Retain explicit positive jellyfish reports for every displayed current
  beach and split them into groups of at most three names.
- Reject duplicate names, duplicate timestamps, conflicting records, and
  jellyfish values that are not tied to a current verified beach record.

## Consequences

The digest can no longer hide a known stricter peripheral flag merely because
three preferred records arrived first. Complete data may take longer to become
available, but the existing 10:40 partial fallback prevents one missing zone
from suppressing all beach information. The change adds no network request,
cache, process, dependency, or source.

The proposed later-day monitor in ADR 0031 remains separate. Its full-beach
baseline can reuse this normalized six-zone result, but this decision does not
authorize or schedule monitoring.
