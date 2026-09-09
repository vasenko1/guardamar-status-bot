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
only a normalized seven-day catalogue. Each list card keeps its normalized
detail URL and whether that detail was read successfully. A new card, a card
whose visible title/date/time/place/link changed, or a prior detail failure
gets one detail request; unchanged cards reuse their saved factual sentence.
The morning and weekend messages read the local catalogue, merge duplicates
with existing official sources, and show the sentence only after a reviewed or
prepared Russian translation exists.

## Consequences

- The morning publication makes no new library request.
- A normal unchanged refresh makes one list request. A refresh with `N` new or
  visibly changed cards makes one list request plus `N` detail requests.
- No HTML, images, source archive, database or page crawl is stored.
- A failed library request simply omits that source; it cannot block the
  digest.
- A teaser is optional and never generated from missing or partial facts.
