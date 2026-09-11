# ADR 0059: Enrich confirmed events from Cultura Guardamar

- Status: Accepted
- Date: 2026-09-10

## Decision

During the existing municipal catalogue refresh, make one bounded public
Facebook Page Plugin renderer request to Cultura Guardamar. The response is a
short timeline, not a page crawl. A post may contribute one explicit, short
Spanish sentence only when its visible title matches an event already
confirmed by the municipal catalogue. It cannot create an event, replace
official date, time or venue facts, or trigger a morning request.

The normalized sentence is retained with the event and translated through the
existing prepared translation cache. If the timeline is unavailable or a post
falls out of it, the prior normalized sentence remains while the event does.
The catalogue records a safe source diagnostic only for a technical fetch or
parse failure. A successful timeline with no matching post remains quiet. A
late catalogue refresh prepares any newly discovered teaser translation before
later previews consume the updated catalogue.

## Consequences

- One extra bounded request during the existing refresh; no browser, cookie,
  token, raw-response storage, scheduler or dependency.
- Ambiguous or missing matches add nothing.
- Morning and weekend consumers read the same enriched municipal snapshot and
  use the same normalized event merger and renderer.
