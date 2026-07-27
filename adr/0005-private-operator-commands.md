# ADR 0005: Private allowlisted operator commands

- Status: Superseded by ADR 0008
- Date: 2026-07-27

## Context

The operator needs to inspect and trigger the MVP from Telegram. Commands must
not expose controls in the existing group or add webhook infrastructure,
another process, or a heavy Telegram framework.

## Decision

The existing Python process receives Telegram message updates with one bounded
standard-library long-poll request.

It accepts `/start`, `/help`, `/status`, `/preview`, and `/send` only when:

- the message is in a private chat;
- the sender's numeric ID is in `TELEGRAM_ALLOWED_USER_IDS`;
- the update is recent enough not to be replayed after a restart.

Group messages and unauthorized users are ignored without a reply. `/preview`
does not change delivery state. `/send` calls the existing guarded daily
delivery path, so it cannot bypass the one-attempt-per-local-date rule. No
update offset is persisted; the freshness check prevents old commands from
being executed after restart.

## Consequences

- The operator can manage the MVP without shell access for routine checks.
- The group remains free of interactive bot responses.
- The runtime gains one idle long-poll HTTP request but no new dependency,
  webhook, server, database, or process.
- Configuration must include at least one trusted numeric Telegram user ID.
