# ADR 0010: Private preview listener

## Status

Accepted

## Context

The operator needs to request a current preview directly from Telegram before
publishing. Telegram cannot deliver a command to an exited process. Periodic
short polling would waste network and delay replies; a webhook would add
infrastructure.

## Decision

- Add a separate optional `listen` process using Telegram `getUpdates` long
  polling with the Python standard library.
- Accept only fresh `/preview` messages in private chats whose sender ID is in
  `TELEGRAM_ALLOWED_USER_IDS`.
- Ignore groups, unauthorized users, stale updates, and every other command.
- Collect the current digest only after an accepted command and reply silently
  to that private chat.
- Never publish to the configured destination or read/write publication state.
- Keep the 07:30 publication process one-shot and independent.
- Add no webhook, Telegram framework, database, or persisted update offset.

## Consequences

The optional listener has one idle network request and a small Python memory
footprint. Android may kill it, so deployment may restart it without affecting
daily publication. Pending commands older than two minutes are acknowledged
but ignored after restart.

## Alternatives rejected

- Manual Termux-only preview: does not meet the direct Telegram workflow.
- Frequent scheduled polling: adds delay and repeated network wakeups.
- Webhook: requires a public endpoint and more operational infrastructure.
