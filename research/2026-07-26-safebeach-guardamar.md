# SafeBeach Guardamar Source

## Question

Can the Morning Digest obtain official Guardamar beach flags and sea
temperature with a lightweight request?

## Sources checked

- [Guardamar del Segura municipality](https://www.guardamardelsegura.es/),
  accessed 2026-07-26; its “Bandera y estado de playas” link redirects to the
  Guardamar SafeBeach page.
- [SafeBeach Guardamar public page](https://info.safebeach.es/guardamar-del-segura),
  accessed 2026-07-26.
- [SafeBeach service description](https://www.safebeach.es/en/), accessed
  2026-07-26; describes live beach-status data managed for municipalities and
  lifeguard services.

## Findings

- The public page embeds a structured `SB_MARKERS` JSON array.
- Each beach item can expose activity state, service-ended state, flag label
  and color, water temperature, and other fields not needed by the digest.
- Multiple Guardamar beaches can have different simultaneous flags.
- The page requires no bot credential, but its public schema has no stability
  guarantee.

## Recommendation

Fetch the bounded public page and parse only the minimum fields. Include only
active, non-ended records and choose the most restrictive known flag. Use the
water temperature from that record. Treat any request or schema failure as an
optional-source failure and omit the beach line.

Confidence is high that the current page is municipality-linked and provides
the required live fields; confidence in long-term schema stability is medium,
so focused fixtures and graceful omission are required.

Later decision: ADR 0006 supersedes the all-Guardamar selection rule with
`Platja Centre / Babilònia` only.
