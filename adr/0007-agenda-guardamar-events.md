# ADR 0007: Agenda Guardamar same-day events

- Status: Accepted
- Date: 2026-07-27

## Context

The canonical digest reserves an optional `📅 События дня:` section. The source
must be official, deterministic, lightweight, and usable without runtime AI,
OCR, or a general news parser.

## Decision

- Use `https://www.agendaguardamar.com/` for official ticketed events.
- Read one bounded programming page and follow at most twelve unique,
  same-host event detail links.
- Extract only the Schema.org event title and `startDate`.
- Keep only events whose `Europe/Madrid` date is today.
- Sort chronologically, deduplicate, and show at most two.
- Truncate unusually long titles deterministically in the formatter.
- Omit the complete section on source failure or when no event is scheduled.
- Do not add source labels to the user-facing message.

## Consequences

- The digest gains useful same-day events without AI or media processing.
- One daily collection may make several small sequential HTML requests, but
  the link count, response sizes, timeouts, output, and memory are bounded.
- The HTML and imperfect JSON-LD require focused fixtures and graceful
  omission.
- This does not provide municipal operational notices or traffic closures.
