# 0002: Optional SafeBeach status

- Status: Accepted
- Date: 2026-07-26

The all-Guardamar flag-selection rule is superseded by ADR 0006. SafeBeach
remains an accepted optional source.

## Context

The digest needs an official Guardamar beach flag and sea temperature without
adding a heavy client or making weather delivery depend on a secondary source.
Guardamar municipality links to a SafeBeach public page containing structured
current beach records.

## Decision

- Fetch the Guardamar SafeBeach public page with standard-library HTTP.
- Read only active, non-ended flag and water-temperature fields.
- Represent Guardamar with the most restrictive active flag and the
  temperature attached to that record.
- Omit the beach line on missing, unknown, oversized, or unavailable data.
- Fetch SafeBeach alongside AEMET, without changing scheduling or delivery.

## Consequences

- The message remains short and conservatively represents differing flags.
- SafeBeach failure cannot block the weather digest.
- The small parser needs fixture tests because the public page schema can
  change.

## Alternatives considered

- List every beach: rejected because it makes the digest noisy.
- Treat SafeBeach as mandatory: rejected because silence for one optional
  section is better than losing the whole weather digest.
- Add a browser or HTML parsing dependency: unnecessary for one bounded
  structured payload.
