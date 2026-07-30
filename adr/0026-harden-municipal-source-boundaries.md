# ADR 0026: Harden municipal source boundaries

- Status: Accepted
- Date: 2026-07-30

## Context

The Mayor channel, Policía Local, municipal poster, and Gemini adapters already
had bounded request sizes but relied on default redirects, accepted unexpected
content types, and reported mostly generic failures. A corrupt poster snapshot
also prevented recovery even when the official source remained available.

## Decision

- Restrict each request and redirect to its existing exact official HTTPS
  hosts.
- Require HTML for Mayor and municipal index pages, PDF for the reviewed police
  document, supported image MIME types for posters, and JSON for Gemini.
- Preserve existing request counts, timeouts, and size limits. Add no retries,
  cache, dependency, or shared generic HTTP framework.
- Give each failure a stable operator-safe code and description without
  exposing response bodies, API keys, or URLs containing secrets.
- Treat a corrupt municipal snapshot as unavailable and rebuild it atomically
  from a valid current official poster. If both paths fail, omit the optional
  events and report a recovery failure.
- Download a poster immediately for a new URL. For an unchanged URL, recheck
  the image and hash only when the local month changes.
- Require the OCR-declared month to match the official poster URL, and accept
  event dates only from that month or the immediately following month.
- Report an atomic snapshot-write failure without discarding already validated
  events from the current run.
- Treat unrecognized Mayor-channel message structure as a source failure and
  require a fixed Gemini response schema for poster OCR.

## Consequences

Unexpected redirects and server error pages can no longer look like valid
municipal data. Private previews identify the failing boundary more precisely.
Recovery from local snapshot damage remains automatic and lightweight.
