# ADR 0012: Monthly municipal agenda snapshot

## Status

Accepted and implemented

## Context

The official Guardamar municipal agenda poster contains events that are absent
from the accompanying HTML text. The poster is a monthly image, so HTML-only
collection is incomplete. The bot must continue showing scheduled events when
the official site is temporarily unavailable, but local OCR is too heavy for
the target Android device.

## Decision

- Treat the official Turismo Guardamar cultural-agenda HTML and its linked
  Ayuntamiento monthly poster as complementary official sources.
- Check the agenda page during the morning run and process the poster only
  when its official URL changes. Hash a newly downloaded image before
  replacing the valid snapshot.
- Use the bounded Gemini Vision API to extract a strict structured event list
  from a new or changed poster. Do not run a local OCR model.
- Store only normalized event facts for the current month and any explicit
  next-month preview: title and explicit activity type in source language,
  date, time range, place, source URL, poster hash, and last successful
  verification time.
- Do not store generated Russian translations. Translate only events selected
  for today's digest.
- Merge poster and HTML events, prefer the more explicit official record, and
  deduplicate by normalized date, time, place, and title.
- On source failure, use the last successfully stored monthly snapshot until
  its covered period ends. This is an explicit exception to the general
  no-stale-municipal-data rule.
- Replace the snapshot atomically after a successful complete refresh. Never
  replace good data with an empty or invalid OCR result.
- Expire events after their end date and remove snapshots after their covered
  month and explicit preview period.
- The `📅 События` section contains at most two events relevant today.
  Routine opening hours and municipal services such as the mobile ecopark are
  not events and do not enter this section.

## Failure policy

- HTML unavailable, valid snapshot present: use the snapshot.
- Poster unavailable, valid snapshot present: use the snapshot.
- Gemini unavailable or OCR invalid: keep the prior valid snapshot.
- No valid snapshot: omit the event section.
- Conflicting dates or unreadable poster content: omit the affected event.

## Consequences

The event section remains useful during short outages and covers more of the
official municipal program. Persistent state expands beyond the publication
date by one bounded agenda snapshot. One image download and one Gemini Vision
request occur only when the monthly poster changes, not every morning.

The accepted tradeoff is that a cancellation published during a source outage
may not be reflected until the next successful refresh.

## Alternatives rejected

- HTML only: demonstrably misses poster-only events.
- OCR every morning: wastes network, model quota, and battery.
- Local OCR: too heavy for the weak Termux device.
- Store translated messages: creates stale copy and translation-maintenance
  problems.
- Treat services and opening hours as events: adds noise to the short digest.
