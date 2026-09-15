# ADR 0044: Public transport change notifications

## Status

Accepted

## Context

The transport guide is already synchronized at 05:00 Europe/Madrid. Urban
lines 1 and 2 are sourced from official municipal PDFs, while the airport
service is sourced from the date-specific Bus Sigüenza planner and its official
fare PDF. Updating the pinned guide in place is useful, but users do not notice
meaningful changes unless a separate public message is published.

The sources have different semantic precision. For urban PDFs the application
can prove that the accepted document and rendered timetable changed, but it
does not parse individual departures, stops, or route changes. The airport
planner exposes structured departures for one exact service date, and the fare
parser intentionally extracts only the standard `TARIFA BASE GENERAL` fare for
Guardamar del Segura to Aeropuerto.

## Decision

- Keep the existing 05:00 transport synchronization unchanged as the source of
  accepted data, then collect notification candidates immediately afterwards.
- Publish at most one aggregated public transport notification at 12:30
  Europe/Madrid.
- Use the fixed heading `🚌 Transport · changes` in Russian as
  `🚌 Транспорт · изменения` and the existing shared Guardamar footer.
- Urban lines notify only when the accepted rendered timetable image changes.
  A PDF hash change with the same rendered image is silent. The text says only
  that the municipality published a new timetable; it never claims a specific
  trip, stop, or route change.
- Airport departure changes are compared only for the same service date. Each
  morning the collector stores tomorrow's structured departures; the next
  morning that baseline is compared with the newly accepted schedule for that
  exact date. Ordinary weekday/weekend differences therefore cannot become
  false change notifications.
- Airport fare notifications compare only the parsed standard base fare. Card,
  pass, senior, discount, or other tariff classes are not inferred or shown.
  The effective date controls whether the message says the new fare will apply
  in the future or already applies.
- Multiple urban, airport, and fare changes are aggregated into one message.
- The first run only establishes baselines and never publishes the already
  existing state as a new change.
- Publication uses a small atomic pending state. Before Telegram delivery the
  state is marked uncertain; automatic resend is disabled if the outcome is
  ambiguous, preventing duplicate public posts after a crash or network
  failure.
- Road closures, temporary diversions, mobility measures, and emergency
  transport disruptions remain outside this subsystem.

## Consequences

The channel receives human-readable transport updates without pretending that
urban PDFs provide structured semantic diffs. Airport departure notifications
remain precise because comparisons are date-for-date, at the cost of one extra
planner request each morning to establish the following day's baseline.

A missed tomorrow-baseline request means exact airport departure-change
notification is skipped for the following day rather than guessed. The pinned
transport guide still updates normally.
