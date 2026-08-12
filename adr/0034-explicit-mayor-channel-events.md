# ADR 0034: Explicit Mayor-channel event announcements

## Status

Accepted and implemented

## Context

Some useful same-day municipal activities are announced only shortly before
they happen and do not appear in Agenda Guardamar or the monthly cultural
programme. On 11 August 2026 the official `@AlcaldeGuardamar` channel
published the 12 August environmental workshop `SERES FASCINANTES DEL
MEDITERRÁNEO` with its date, `09:00–13:00` time and Playa Centro location.
The existing adapter already downloaded this bounded public page but accepted
only Fiestas de Barrio as events.

Treating every Mayor-channel post as an event would turn the digest into a
general news feed and could misclassify reports about completed activities.

## Decision

- Reuse the existing single bounded public HTML read; add no source, request,
  dependency, cache, poller or resident process.
- Accept a general municipal announcement only when the text contains an
  invitation, a quoted title, an explicit day and month, a valid start time,
  an explicit place and, when present, the correct weekday and year.
- Keep only occurrences matching the current Guardamar date. Reject invalid
  times, missing fields, retrospective reports and overnight ranges that are
  not explicitly supported.
- Preserve the source title when no reviewed Russian title exists. A small
  exact mapping may translate an independently reviewed occurrence without
  changing other source facts.
- Merge accepted items through the existing cross-source event deduplication.
- Keep all prior narrow Mayor-channel rules for bathing transitions, market
  exceptions and Fiestas de Barrio unchanged.

## Consequences

Late official activities can reach the Morning Digest without Facebook
scraping or AI at publication time. The strict field and invitation contract
will intentionally miss loosely worded announcements; this is preferable to
publishing ordinary municipal news as an event.
