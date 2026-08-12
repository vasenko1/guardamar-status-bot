# 0035: UV-index and sunrise/sunset rows in the weather block

- Status: Accepted
- Date: 2026-08-12

## Context

The 2026-08 product review identified two weather-block additions with no
new source cost. AEMET's approved municipal daily forecast documents a
`uvMax` field alongside the fields the bot already parses, and sunrise and
sunset are pure functions of the calendar date computable on-device. For a
beach town, a high UV value is decision-relevant safety information; the
daylight span is broadly useful year-round.

## Decision

- Parse `uvMax` opportunistically inside the existing municipal daily
  normalization. A missing or implausible value (outside 0–16) yields no
  value, never an error, and never a new request. The dedicated AEMET UVI
  product is not requested; it remains the documented fallback only if the
  municipal field proves absent in practice.
- Render one compact `УФ:` row only when the index is 6 or higher, with the
  WHO category names `высокий` (6–7), `очень высокий` (8–10), and
  `экстремальный` (11+). Lower values are routine and stay silent.
- Compute sunrise and sunset with the standard NOAA sunrise equation in a
  small stdlib-only module (`sun.py`) for the fixed Guardamar coordinates,
  and render one `Солнце:` row. The values are injected into the weather
  record at collection time; the renderer stays deterministic and the AEMET
  snapshot round-trips both fields.
- Both rows live inside the weather block after the sea row, keeping the
  bold-label, no-icon internal-row convention.

## Consequences

- Benefits: two useful rows with zero additional network requests, AI use,
  or schedule changes; the UV row follows silence-over-noise by appearing
  only when actionable.
- Costs: the daily-forecast normalizer tuple grows by one field, and the
  canonical layout gains two optional rows that tests must cover.
- Follow-up: verify `uvMax` presence in the live payload via the operator
  preview after deployment; if AEMET never supplies it, decide on the UVI
  product with a follow-up ADR instead of silently adding a request.

## Alternatives considered

- Requesting the dedicated provincial UVI product — rejected for now: it
  adds one bounded request per run for data the municipal payload is
  documented to contain.
- Showing every UV value — rejected: values below the WHO high threshold
  are routine noise.
