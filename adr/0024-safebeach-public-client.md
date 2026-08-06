# ADR 0024: Minimal public SafeBeach client

- Status: Accepted
- Date: 2026-07-30
- Superseded in part by: ADR 0032

## Context

Guardamar municipality links to a public SafeBeach page. The page embeds the
current beach records in HTML but does not publish a stability contract for
that structure. The application already invokes the beach update command every
five minutes during a bounded morning window, so an additional retry layer
would increase load and complexity without adding a distinct recovery path.

## Decision

- Keep the municipality-linked public page as the approved MVP source.
- Make one standard-library HTTPS request per invocation with a ten-second
  timeout and 512 KiB response limit.
- Accept only the exact SafeBeach public host, including redirects, and require
  an HTML response.
- Require the page's calendar date to equal the local `Europe/Madrid` date.
  This rejects an old complete page but is not treated as a per-record
  synchronization date. Do not retain earlier responses or status history.
- Decode `window.SB_MARKERS` from its fixed assignment with the standard JSON
  decoder. Do not run JavaScript, preserve cookies, or automate a browser.
- Return at most three active, non-ended, timestamped records. Prioritize
  Centre / Babilònia, Roqueta, and Vivers; fill missing slots from Montcaio,
  Camp, and Ortigues without renaming or averaging them.
- For same-color duplicate records, keep the newest timestamped record. Omit
  one beach when current duplicate colors conflict or its recognized text and
  HEX flag colors disagree.
- Treat no eligible current record as a valid empty result. Treat transport,
  type, date, size, and schema failures as optional-source failures.
- Add no internal retry or cache. The existing external five-minute checks are
  the recovery mechanism.

## Consequences

The client remains one small dependency-free request and parser. It fails
closed on stale or contradictory safety data without hiding valid data for
other Guardamar beaches. A future public-page schema change can still require
a fixture update, but it cannot silently become a normal-looking flag.
