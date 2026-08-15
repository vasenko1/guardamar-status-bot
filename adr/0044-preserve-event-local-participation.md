# ADR 0044: Preserve event-local participation details

## Status

Accepted and implemented

## Context

Todo Cultura can publish both a broad daily programme and separate pages for
individual activities on the same date. The rolling collector downloaded at
most three full pages and treated the first accepted page as covering the date
for every other candidate. A newer generic page could therefore suppress an
older workshop page that contained the audience, registration contact,
capacity, or admission details readers needed.

On 15 August 2026 this left the electric-guitar workshop with only its time and
name even though its event page explicitly stated ages 12 through 30, beginner
and improvement formats, group practice, and registration through Centro
Social Juvenil or WhatsApp.

## Decision

- Keep the existing limits of one 100-item metadata read, at most three full
  event pages per refresh, a seven-day rolling window, and 12,000 extracted
  source characters.
- Among candidates for the nearest unprocessed date, prioritize lightweight
  metadata that explicitly signals an audience or age, registration,
  reservation, capacity, admission, price, workshop, course, route, or guided
  visit. Freshness breaks ties after usefulness; it does not displace an older
  actionable event page merely because a generic page was published later.
- Track full-page completion per candidate. A successfully processed page may
  add the date to observability state, but it must not mark distinct same-date
  candidates as processed. Identical dated sections remain hash-deduplicated
  within the bounded extraction input.
- Leave candidates beyond the three-page limit pending so subsequent scheduled
  refreshes can collect them without increasing the per-run request burst.
- Accept an explicit registration row only when it contains a phone or email
  contact, bind it to a nearby event row, and preserve explicit age ranges,
  minimum ages, and limited-capacity wording. Never invent missing conditions.
- Reopen the bounded current candidate index once through parser version 7 so
  deployed catalogs can recover details hidden by the former date-wide gate.
- Keep one exact reviewed correction for the current guitar workshop so an
  in-place refresh can repair today's message even during a supplemental-source
  outage.

## Consequences

Future same-day event pages are collected over one or more normal refreshes
instead of being permanently skipped. Useful participation facts become more
likely to occupy the three available detail slots, while network burst, model
input, dependencies, cron frequency, and public message bounds remain
unchanged.

The complete candidate set may take several scheduled runs when more than
three distinct pages are pending. This is intentional back-pressure. The
official municipal catalogs remain primary, and Todo Cultura remains an
optional lower-priority supplement that fails closed.

## Alternatives rejected

- Increase the full-page limit: faster backfill at the cost of a larger mobile
  request and model burst.
- Treat the newest page as complete for its entire date: efficient but loses
  facts held only by separate activity pages.
- Copy every free-form activity description into the digest: creates long,
  inconsistent messages and weakens evidence boundaries.
- Add a per-event reviewed correction only: repairs one occurrence but leaves
  the selection defect in place.
