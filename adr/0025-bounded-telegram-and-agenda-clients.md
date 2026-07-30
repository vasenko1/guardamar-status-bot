# ADR 0025: Bounded Telegram and Agenda clients

- Status: Accepted
- Date: 2026-07-30

## Context

Telegram send, delete, and update calls duplicated protocol handling, while
Agenda Guardamar could read up to twelve event pages sequentially. Both paths
run on a weak Android device and must fail clearly without frameworks, caches,
or unbounded work.

## Decision

- Route all Telegram operations through one standard-library JSON client.
- Accept only HTTPS responses and redirects on `api.telegram.org`, bound
  response size, validate response type and structure, and expose stable
  operator-safe failure codes without server text or tokens.
- Retry only Telegram sends and only for rate limits or transient server and
  transport failures. Keep delete and long-poll retry decisions with callers.
- Accept Agenda pages only from its two official HTTPS host forms, require
  bounded HTML, and parse complete `application/ld+json` documents. Repair
  only the site's observed extra property quote and trailing commas before
  rejecting malformed JSON-LD.
- Accept only Schema.org event types and omit the site's known technical
  publisher identifier when it appears in the venue field.
- Keep the existing limit of twelve Agenda detail links and two published
  events, but read at most three detail pages concurrently.
- Add no dependency, cache, connection pool, or general HTTP abstraction.

## Consequences

All Telegram calls receive the same safety checks and diagnostics. Agenda no
longer accumulates every detail timeout serially, while its request count and
output contract remain unchanged. Three short worker threads are an accepted
temporary cost only during event collection.
