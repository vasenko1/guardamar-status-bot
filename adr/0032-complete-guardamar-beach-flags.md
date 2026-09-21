# ADR 0032: Complete Guardamar beach flag coverage

- Status: Accepted; publication-timing rules superseded by ADR 0064 on 2026-09-21
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
- The former requirement to wait for all six zones before 10:40 is
  superseded by ADR 0064. Any valid current response with at least one known
  beach may create or refresh the separate beach root during 10:10–10:40.
- Never merge beach records from different SafeBeach responses. Each root
  edit reflects one whole valid current response.
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

The product retains every valid current Guardamar beach record that the latest
SafeBeach response supplies. Partial current coverage is published immediately
rather than withheld for completeness, and separate responses are never
combined into a synthetic current snapshot.

The later-day monitor in ADR 0031 remains separate. Its baseline reuses the
latest published beach-root facts, which may contain any valid current subset
of the six known zones; this decision does not authorize or schedule
monitoring.
