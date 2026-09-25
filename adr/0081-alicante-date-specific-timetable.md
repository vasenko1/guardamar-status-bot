# ADR 0081: Date-specific Guardamar-Alicante timetable

## Status

Accepted

## Context

The linked transport guide already has a Guardamar ↔ Alicante card, but it was
static. The bot therefore could not show the departures for the current date or
feed meaningful changes into the existing transport-notification workflow.

Two candidate sources were tested against live data:

- the Generalitat Valenciana interurban GTFS contains Guardamar and Alicante
  stops, but the current feed does not attach the Guardamar bus-station stop to
  usable stop_times/trips for this route, so it cannot prove the timetable;
- the Avanza/Costa Azul public planner accepts an ordinary HTML form POST for an
  exact route and date and returns a compact schedule table with departure,
  arrival and price. No browser or JavaScript execution is required.

The existing transport lifecycle is already fixed at 05:00 for synchronization
and 08:42 for public change notifications. A second polling loop would duplicate
state and delivery logic.

## Decision

- Extend the existing 05:00 `sync-transport` run; add no cron row, daemon,
  browser, OCR or generic notification framework.
- Use the Avanza/Costa Azul public planner as the single Alicante source.
  Fetch the initial form once and submit four bounded requests per daily run:
  today and tomorrow in both directions.
- Validate the requested date and both route names in the returned page. Accept
  a schedule only when there is exactly one recognizable departure/arrival
  table and 1..64 valid rows.
- Treat price as optional within an otherwise valid timetable. If every
  validated row in both directions has one price, show that exact price; if
  prices vary, show the minimum as `от`. If price markup becomes ambiguous,
  keep the timetable but omit the price.
- Keep only normalized current and next-day snapshots. Do not persist raw HTML.
- Edit the existing managed `alicante` Telegram message in place. If it was
  deleted, recreate it under the existing uncertain-delivery rules.
- Show the explicit service date and weekday, all validated departures in both
  directions, the fare when validated, endpoint map links, the planner link for
  another date, the transport back-link and the standard group footer.
- Store tomorrow's normalized Alicante snapshot in the existing transport
  notification state. On the next 05:00 run compare it only with the newly
  accepted snapshot for that same service date. This prevents ordinary
  weekday/weekend differences from becoming false change alerts.
- Feed proven departure and fare changes into the existing
  `transport_notifications.py` buckets. The first comparable baseline is
  silent. Missing or invalid source data never proves a cancellation or price
  change.
- Do not infer a named summer/winter period from different daily departure
  arrays. A future `period_changed` event for Alicante requires an explicit
  authoritative rule with a known effective date.

## Consequences

The Alicante card becomes useful every day while preserving the existing
05:00 → 08:42 transport lifecycle.

The source path is intentionally small: one initial GET plus up to four HTML
POSTs in the daily transport sync. There is no second source, large GTFS
download, browser runtime, source-history database or new notification
subsystem.

If tomorrow cannot be validated while today can, today's card may still update;
the missing tomorrow snapshot simply means there is no comparable baseline for
the following day's Alicante alert.
