# ADR 0081: Date-specific Guardamar-Alicante timetable

## Status

Accepted

## Context

The linked transport guide already has a Guardamar ↔ Alicante card, but it was
static and therefore could not show the departures for the current date or feed
meaningful changes into the existing transport-notification workflow.

The Generalitat Valenciana open-data catalogue publishes the interurban-bus
GTFS feed daily. The dataset explicitly includes communicated route and
point-timetable modifications and provides service dates for the following ten
days. The Avanza/Costa Azul public planner remains the passenger-facing source
for the basic ticket price.

The existing transport lifecycle is already fixed at 05:00 for synchronization
and 08:42 for public change notifications. A second polling loop would duplicate
state and delivery logic.

## Decision

- Extend the existing 05:00 `sync-transport` run; add no cron row, daemon,
  browser, OCR or generic notification framework.
- Download one bounded official Generalitat GTFS ZIP and extract only direct
  Guardamar bus-station ↔ Alicante bus-station departures for today and
  tomorrow. Endpoint stops must match both the locality name and conservative
  coordinate bounds; Alicante airport stops are explicitly excluded.
- Keep only normalized current and next-day snapshots. Do not persist raw GTFS
  or planner HTML.
- Edit the existing managed `alicante` Telegram message in place. If it was
  deleted, recreate it under the existing uncertain-delivery rules.
- Show the explicit service date and weekday, all validated departures in both
  directions, endpoint map links, the planner link for another date, the
  transport back-link and the standard group footer.
- Read the optional basic one-way fare from the bounded Avanza/Costa Azul
  public planner. Submit both directions for the exact service date. If every
  validated service has one amount, show that amount; otherwise show the
  minimum as `от`. A planner failure removes the price from the new accepted
  snapshot rather than inventing or carrying a stale price across service
  dates.
- Store tomorrow's normalized Alicante snapshot in the existing transport
  notification state. On the next 05:00 run compare it only with the newly
  accepted snapshot for that same service date. This prevents ordinary
  weekday/weekend differences from becoming false change alerts.
- Feed proven departure and fare changes into the existing
  `transport_notifications.py` buckets. The first comparable baseline is
  silent; a missing source row or source failure never proves cancellation.
- Do not infer a named summer/winter period from different daily departure
  arrays. A future `period_changed` event for Alicante requires an explicit
  authoritative rule with a known effective date.

## Consequences

The card is useful every day while preserving the existing 05:00 → 08:42
transport lifecycle. Schedule and fare alerts reuse the same delivery,
grouping, direct-card linking and uncertain-send protections already used by
the other monitored transport routes.

The GTFS ZIP is the largest input in this path, but it is fetched only once per
day, is size-bounded, and only the five required members are streamed. The
Avanza fare is optional: a planner markup change cannot suppress the official
GTFS timetable.
