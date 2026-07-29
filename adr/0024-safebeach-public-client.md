# ADR 0024: Minimal public SafeBeach client

- Status: Accepted
- Date: 2026-07-30

## Context

Guardamar municipality links to a public SafeBeach page. The page embeds the
current beach records in HTML but does not publish a stability contract for
that structure. The application already invokes the beach update command every
five minutes during a bounded morning window, so an additional retry layer
would increase load and complexity without adding a distinct recovery path.

## Decision

- Keep the municipality-linked public page as the approved MVP source.
- Make one standard-library HTTPS request per invocation with a ten-second
  timeout and 256 KB response limit.
- Accept only the exact SafeBeach public host, including redirects, and require
  an HTML response.
- Require the page date to equal the local `Europe/Madrid` date. Do not retain
  earlier responses or status history.
- Decode `window.SB_MARKERS` from its fixed assignment with the standard JSON
  decoder. Do not run JavaScript, preserve cookies, or automate a browser.
- Select only active, non-ended Centre / Babilònia, Roqueta, and Vivers
  records. Preserve partial valid results.
- Collapse identical duplicates. Omit one beach when duplicate records
  conflict or its recognized text and HEX flag colors disagree.
- Treat no active selected record as a valid empty result. Treat transport,
  type, date, size, and schema failures as optional-source failures.
- Add no internal retry or cache. The existing external five-minute checks are
  the recovery mechanism.

## Consequences

The client remains one small dependency-free request and parser. It fails
closed on stale or contradictory safety data without hiding valid data for
other selected beaches. A future public-page schema change can still require a
fixture update, but it cannot silently become a normal-looking flag.
