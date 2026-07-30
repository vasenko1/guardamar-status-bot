# ADR 0021: Two-stage daily message replacement

- Status: Accepted
- Date: 2026-07-29
- Supersedes: ADR 0016 and the single-run state rules in ADR 0008

## Context

A 07:30 briefing is useful before SafeBeach normally publishes lifeguard data.
Waiting until 10:00 makes routine city information late, while posting two
independent messages leaves stale duplicate information in the group.

## Decision

- Publish one complete briefing without operational SafeBeach rows at 07:30.
- In the 20 June–14 September season, invoke a short update command at 10:10
  and every five minutes through 10:40.
- Each invocation checks SafeBeach first. Before 10:40, replacement requires
  active, non-ended flags with plausible update times for Centre / Babilònia,
  Roqueta, and Vivers together.
- If that preferred set is incomplete, exit immediately and let the next
  five-minute invocation retry. At 10:40, the retry window expires and any
  non-empty valid selected Guardamar beach set is usable. Missing beaches are
  omitted and their values are never inferred.
- After SafeBeach succeeds, or after the final attempt, check
  `@AlcaldeGuardamar` once for an explicit bathing-status transition published
  after the morning message.
- If neither source supplies an update, keep the morning message.
- If either supplies an update, recollect the remaining sources once, send a
  full replacement with normal notification, store its Telegram message ID,
  and only then delete the morning message.
- Use the shared AEMET adapter policy recorded in ADR 0023 for the 07:30
  message, replacement, and private preview. If mandatory forecast recovery
  fails, retain the exact
  published 07:30 copy for unchanged sections and add only the verified
  SafeBeach and/or Mayor update.
- If deletion fails, a later invocation retries deletion without resending.
- Keep one atomic JSON state containing only the current date, morning
  publication time and rendered copy, message IDs, and deletion result.
- Use external cron invocations. Do not keep a process asleep between retries.

## Consequences

The group normally contains one current full message, city information arrives
early, and the replacement normally contains all three preferred beaches.
Persistently missing records still allow a truthful partial replacement at
10:40. Seasonal checks add at most seven small SafeBeach requests and no idle
runtime.
Telegram still has an unavoidable edge when a successful send response is lost
before its message ID can be stored.

## Rejected alternatives

- One 10:00 message: city information arrives unnecessarily late.
- Two permanent daily messages: duplicates most content and leaves stale data.
- Edit the morning message: an edit does not provide the desired notification.
- One process sleeping for 30 minutes: less recoverable than cron invocations.
