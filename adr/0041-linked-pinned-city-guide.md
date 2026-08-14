# 0041: Linked pinned city guide

- Status: Accepted
- Date: 2026-08-14

## Context

Residents need two stable references, public cameras and direct transport,
without expanding the daily Morning Digest. Telegram links can connect a short
pinned root to detailed bot-authored messages, but the target message IDs exist
only after delivery. A partial failure must not create a second complete set on
the next attempt. The weak Android runtime must not gain a scheduler, browser,
media converter, or recurring source collector.

## Decision

Add one explicit operator-run publication command for a static linked guide.
It reconciles the detailed messages, transport navigator and compact root into
one bidirectional link graph, then pins the root without a service notification.
Every route detail links back to the transport navigator; the camera list and
transport navigator link back to the compact root. One small atomic state stores
only the destination and message IDs. Each replacement ID is saved immediately,
so a later invocation resumes. An exact Telegram `message not found` response
recreates the deleted bot-authored message, then bounded reconciliation updates
every dependent link. `message is not modified` is successful idempotence;
unrelated HTTP 400 errors fail closed and never create a duplicate.

The optional private listener also accepts `/pinned_preview` from the existing
allowlist. It sends the exact text sequence silently to that private chat but
does not publish, pin, or write guide state. A one-shot CLI command provides the
same private preview for the single configured operator.

The first version is text-only. Attachments are allowed only when the carrier
publishes a current image file. PDFs, locally rendered PDF pages, date-specific
search screenshots, and generated timetable images are excluded.

## Consequences

- The group receives one set of detailed messages on first publication.
- Later copy changes edit that set instead of creating duplicates.
- Accidental deletion of one or several managed messages is repaired on the
  next manual publication; links and the pinned root converge to replacement
  IDs before success is reported.
- A private supergroup or public group username is required for internal links.
- Publication is manual and independent of Morning Digest scheduling.
- Static timetable facts still require source review before copy changes.
- No new dependency, recurring request, background process, or image pipeline
  is introduced.

## Alternatives considered

- Put all details in one pinned message: too wide and difficult to scan.
- Use bot deep links: opens a private bot conversation instead of the group
  context and does not match the approved navigation model.
- Render operator PDFs as images: explicitly rejected because the public media
  would no longer be an image published by the operator.
- Recreate every message on each update: leaves duplicates and makes partial
  failure recovery unsafe.
