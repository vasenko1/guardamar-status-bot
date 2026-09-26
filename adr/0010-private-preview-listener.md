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
- Expose stable operator-safe source and stage codes for failed consulted
  sources. Successful previews append diagnostics after the digest; a fatal
  AEMET failure returns its code instead of a digest.
- A code may include a safe HTTP or API status, but never a URL, credential,
  response body, traceback, or raw transport error.
- Keep the 07:30 publication process one-shot and independent.
- Add no webhook, Telegram framework, database, or persisted update offset.

## Consequences

The optional listener has one idle network request and a small Python memory
footprint. It is a long-lived Python process: imported application modules stay
in memory until the listener exits. Therefore a Git fast-forward does not make
new preview code active inside an already-running listener.

Any production deployment that changes Python code reachable from `/preview`
must restart the `guardamar-preview` runit service and verify the replacement
`telegrambot listen` process. One-shot CLI commands such as
`python -m telegrambot preview` and `refresh-current` start fresh interpreters
and therefore cannot be used as evidence that the resident listener reloaded
the deployment. Android may also kill the listener independently; restarting it
does not affect daily publication. Pending commands older than two minutes are
acknowledged but ignored after restart.

## Alternatives rejected

- Manual Termux-only preview: does not meet the direct Telegram workflow.
- Frequent scheduled polling: adds delay and repeated network wakeups.
- Webhook: requires a public endpoint and more operational infrastructure.
