# ADR 0049: Preserve dated ongoing activities

Date: 2026-08-31

## Decision

Retain municipal `municipal_service` records when they have a verified
multi-day date range. Render them in the Morning Digest with the active-until
date and every validated place, schedule, admission, registration, and ticket
fact. Continue excluding one-day routine opening rows and records without a
bounded date or usable source evidence.

## Reason

The summer environmental volunteer campaign ran through 31 August but was
discarded as a municipal service before rendering. The same loss would affect
future campaigns and bounded ticket-sale windows.

## Consequences

Ongoing public activities remain visible on each applicable day without
inventing a daily timetable. Their end date makes the scope clear, while
existing strict evidence and admission validation continues to protect the
message from incomplete or guessed details.
