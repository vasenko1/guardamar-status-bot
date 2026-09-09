# ADR 0058: Read AM Guardamar posts as a compact public-event supplement

- Status: Accepted
- Date: 2026-09-10

## Context

Agrupación Musical Guardamar publishes its own public concerts, performances
and similar events through a WordPress REST endpoint. Publication timestamps
are not event dates, while posts may also announce enrolment, internal news or
past activity.

## Decision

Within the existing 05:10 event refresh, request the twelve most recently
modified posts from `https://amguardamar.es/wp-json/wp/v2/posts`. Keep only
plain-text, normalized metadata for posts that name Guardamar, contain a
future date within 45 days and describe a public musical event. Keep the post
ID, publication date, modification date, source link, title, short excerpt,
categories, tags and media ID; do not retain HTML, images or a source archive.

For a new or modified candidate, reuse the existing strict text-event
extraction and evidence validator. An unchanged post reuses its prior
normalized facts. The existing event merge and translation cache decide the
published row, so this source cannot duplicate a municipal or library event.

## Consequences

- The 07:30 message and weekend digest read local facts only.
- A failed or invalid response omits only this optional source.
- Enrolment, educational and retrospective posts do not become city events.
- No scraper, feed fallback, browser runtime, image processing or general
  source framework is introduced.
