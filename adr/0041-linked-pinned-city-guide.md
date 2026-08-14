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
It sends or edits the detailed messages first, builds their Telegram links,
then sends or edits the transport navigator and compact root, and finally pins
the root without a service notification. One small atomic state stores only the
destination and message IDs. Each ID is saved immediately after a successful
send, so a later invocation resumes. A missing bot-authored message is replaced
after Telegram returns HTTP 400; other errors fail closed.

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
