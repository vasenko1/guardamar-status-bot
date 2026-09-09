# ADR 0057: Read the official library agenda as a small cached event source

- Status: Accepted
- Date: 2026-09-09

## Context

The Biblioteca Pública Municipal de Guardamar publishes dated exhibitions,
films and other activities on its own official agenda. The municipal catalogue
may contain a short version of the same event, but the library page supplies a
more precise title, venue and, on its detail page, occasionally one useful
factual sentence.

## Decision

Refresh the official list once with the existing 05:10 event task and store
only a normalized seven-day catalogue. For an event active on that date, read
at most its one detail page and retain only one complete factual source
sentence. The morning and weekend messages read the local catalogue, merge
duplicates with existing official sources, and show the sentence only after a
reviewed or prepared Russian translation exists.

## Consequences

- The morning publication makes no new library request.
- No HTML, images, source archive, database or page crawl is stored.
- A failed library request simply omits that source; it cannot block the
  digest.
- A teaser is optional and never generated from missing or partial facts.
