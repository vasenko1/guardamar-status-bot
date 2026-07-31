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
- Store only normalized event facts for the current month, any explicit
  next-month preview, and still-relevant prior-poster events through a
  seven-day transition horizon: title and explicit activity type in source
  language, date, time range, place, source URL, poster hash, and last
  successful verification time.
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
- The `📅 События дня:` section contains every deduplicated verified event
  relevant today; the former product limit of two is superseded. Routine
  opening hours and municipal services such as the mobile ecopark are not
  events and do not enter this section.
- A reviewed official text-agenda schedule may correct missing poster OCR
  hours for a specific event. Never infer event hours from general venue
  opening hours.
- On the explicit end date of a multi-day event, render the compact
  `Последний день:` prefix. One-day events and unknown end dates are unchanged.

## Failure policy

- HTML unavailable, valid snapshot present: use the snapshot.
- Poster unavailable, valid snapshot present: use the snapshot.
- Gemini unavailable or OCR invalid: keep the prior valid snapshot.
- No valid snapshot: omit the event section.
- Conflicting dates or unreadable poster content: omit the affected event.
- A fact manually confirmed in the accompanying official text agenda may
  receive a narrow poster-specific correction in code. The correction must
  name the exact poster, preserve the official wording, have a regression
  test, and must not trigger repeat OCR.
- A reviewed current-month text-agenda record may remain eligible through its
  explicit end date when the page advances to next month's poster early.
- A successful next-poster extraction merges, rather than replaces,
  unexpired prior-poster facts occurring within the next seven days.

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
