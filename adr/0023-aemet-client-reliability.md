# ADR 0023: Protocol-aware AEMET client recovery

- Status: Accepted
- Date: 2026-07-29
- Supersedes: the fixed two-minute AEMET retry rule in ADR 0021

## Context

AEMET OpenData uses a two-step protocol: an authenticated metadata request
returns a short-lived product URL. Fixed retries treated permanent and
temporary failures alike, delayed previews unnecessarily, and could reuse no
longer valid product state. Forecast periods of six hours or more are UTC.

## Decision

- Request the four approved products sequentially with standard-library HTTP.
- Send the API key only to the metadata endpoint.
- Bound every request by time and response size and accept only HTTPS AEMET
  hosts, including redirects.
- Retry the complete metadata-plus-product operation only after a timeout,
  network failure, `429`, `5xx`, or an expired temporary product URL.
- Use short exponential delays, or honor `Retry-After` when it fits the
  process budget. Never retry earlier than a longer server instruction.
- Allow three attempts for the mandatory daily forecast and two for each
  optional product. Do not retry authentication, ordinary no-data, malformed,
  oversized, stale-date, or failed-validation responses.
- Normalize and validate inside the retry boundary. Convert eligible UTC
  forecast periods to `Europe/Madrid`.
- Log only status failures returned by AEMET. Operator previews may still
  report safe transport or validation diagnostics without raw URLs or bodies.
- Do not cache temporary URLs or product payloads.

## Consequences

Normal runs remain four small sequential products with no added dependency.
Short outages and rate limits receive bounded recovery, while permanent errors
fail quickly. The mandatory daily product remains the only AEMET failure that
can block a fresh first publication; optional observation, warning, and beach
products degrade independently.
