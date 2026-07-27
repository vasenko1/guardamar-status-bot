# 0001: Daily Telegram delivery

- Status: Superseded by ADR 0008
- Date: 2026-07-26

## Context

The Morning Digest must send once each morning from a weak Android device.
Android may stop the process, and a failed HTTP response can leave delivery
outcome uncertain. The MVP has one destination and no inbound interaction.

## Decision

- Run one lightweight Python scheduler process in `Europe/Madrid`.
- Send with the Telegram Bot API using standard-library HTTP.
- Configure one destination and one morning time; default to `08:00`.
- Catch up after a late start only before local noon.
- Atomically claim the local date before source collection.
- Never schedule another run for a claimed date, regardless of outcome.
- Allow at most three bounded HTTP attempts inside the claimed run.
- Store only local date, status, and update time in one small JSON file.

## Consequences

- Restarts and uncertain sends do not create a later duplicate.
- A crash after the claim but before a confirmed send can cause a missed day.
  This is the deliberate cost of favoring duplicate prevention.
- The process needs no database, Telegram framework, webhook, or public server.

## Alternatives considered

- Claim only after successful delivery: rejected because a crash after Telegram
  accepts the message could cause a duplicate.
- SQLite: unnecessary for one small state record.
- Webhooks or a job service: unnecessary infrastructure for the MVP.
