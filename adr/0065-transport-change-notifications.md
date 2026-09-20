# ADR 0065: Public transport change notifications

## Status

Accepted, amended 2026-09-20

## Context

The transport guide is synchronized at 05:00 Europe/Madrid. The bot has
machine-comparable accepted state for municipal lines 1 and 2 and for the
Guardamar to Alicante-Elche airport service. Other transport cards remain
useful navigation, but a card alone is not evidence that its timetable, route
or fare can be monitored safely.

## Decision

- Keep the 05:00 transport synchronization and collect notification candidates
  from its accepted state immediately afterwards.
- Publish at 08:42 Europe/Madrid.
- Track only routes for which accepted comparable state exists. Today this is
  line 1, line 2 and the airport route. Alicante, Elche, the south/Zenia route,
  Orihuela, hospital and university cards stay notification-silent until a
  bounded reliable adapter is implemented.
- Store transport changes as small domain events. Current event families are
  timetable/departure changes, deterministic reviewed seasonal-period changes
  and the standard airport base-fare change. A future structured route adapter
  can add route-change events without adding another notification subsystem.
- Group events by resident meaning, not by source. One run may therefore send
  separate messages for schedule changes, route changes and fare changes.
- Link each named route directly to its current Telegram route card. Event
  state stores stable route/card keys, never Telegram URLs; links are resolved
  from `PinnedGuideState` immediately before sending.
- A missing/uncertain route card fails closed. Do not fall back to an external
  planner URL.
- Urban lines notify on a changed accepted rendered timetable image. PDF
  metadata/hash churn with the same rendered image is silent. Because the PDF
  is not semantically parsed, the public message never invents the exact
  changed departure, stop or route.
- Reviewed line 1/2 cards also have a deterministic summer/regular service
  period. A real transition can notify even when the timetable image itself is
  unchanged. An unreviewed new PDF does not support this claim.
- For an unreviewed urban PDF, the card must not display an old hard-coded
  route summary as authoritative; it points users to the accepted timetable
  image for current route/stops/times.
- Airport departure changes are compared only for the same service date using
  the date-specific Bus Sigüenza planner baseline.
- Airport fare notifications compare only the parsed standard
  `TARIFA BASE GENERAL`; discount/card/senior fares are not inferred.
- A first baseline is silent. Source/card disappearance alone never means
  cancellation.
- Multi-message delivery keeps per-message `pending/uncertain/sent` state.
  Before each Telegram send that item is persisted as uncertain. HTTP 429 may
  safely return it to pending; an ambiguous result blocks automatic resend
  without duplicating already-sent sibling messages.
- Temporary closures, emergency diversions and event traffic measures stay in
  the existing mobility/emergency subsystem.

## Consequences

Users receive short semantic transport notices that link directly to the
affected route card. Coverage grows only when a route acquires a source whose
facts can actually be compared. The design remains one short-lived state
machine with no daemon, database, OCR route inference or generic notification
framework.
