# ADR 0082: Date-specific Elche and Orihuela transport cards

## Status

Accepted

## Context

The transport guide already linked Guardamar ↔ Elche and Guardamar ↔ Orihuela,
but both cards were static. The existing Alicante implementation established
the accepted lifecycle: refresh in the 05:00 transport sync, keep only current
and next-day normalized state, compare the same service date, and publish
meaningful schedule/fare changes through the existing 08:42 notification flow.

The two routes have different authoritative operators and must not be forced
through one source adapter:

- Elche: Avanza/Costa Azul public planner.
- Orihuela: Bus Sigüenza exact-date search plus its official CE-714 tariff PDF.

## Decision

- Add no cron row, daemon, browser, OCR or notification subsystem.
- Reuse only a small shared managed-card/state lifecycle for the two new exact
  date cards. Source parsing stays operator-specific.
- Elche queries the proven Avanza HTML form for today and tomorrow in both
  directions. A validated price is shown only when both directions provide a
  usable fare.
- Orihuela queries Bus Sigüenza once per requested date; each response must
  contain exactly the Guardamar→Orihuela and Orihuela→Guardamar panels with
  bounded, unique, sorted departures.
- Orihuela price is read only from the official CE-714 tariff PDF and only from
  the validated `TARIFA BASE GENERAL` Guardamar↔Orihuela row. The current
  reviewed distance pattern identifies the 37 km row. A changed PDF is accepted
  only after a second identical download and successful parsing.
- Today is required for a card refresh; tomorrow is optional. Source failure
  never proves a cancellation.
- Store only normalized current/next snapshots and tariff metadata; do not
  persist raw HTML or PDF bytes.
- The first next-day baseline is silent. On the following morning compare only
  that same service date, preventing normal weekday/weekend schedules from
  generating false alerts.
- Departure and fare changes reuse `transport_notifications.py`; named
  seasonal periods are not inferred from daily timetable differences.

## Consequences

Elche and Orihuela behave like the existing Alicante card from the resident's
perspective while preserving their real operator sources. The 05:00 transport
sync remains the only refresh point and 08:42 remains the only public
notification publisher.
