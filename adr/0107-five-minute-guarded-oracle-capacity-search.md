# 0107: Five-minute guarded Oracle A1 capacity search

- Status: Accepted
- Date: 2026-10-11
- Related: ADR 0061, ADR 0063, ADR 0098

## Context

Our Madrid 3 capacity hunter has repeatedly received `Out of host capacity`.
A 15-minute cadence can miss short-lived host-capacity windows. The existing
GitHub schedule is best-effort; production logs showed that Termux backstop
dispatches produced most actual runs. PR 362 added per-run 6 GB, 2 GB, and
diagnostic-only 1 GB host-capacity observations.

At five-minute cadence, the former Termux ten-minute recency gate would
suppress recovery of missed GitHub schedule slots. OCI API throttling
(`429 TooManyRequests`) must not cause an automatic retry storm.

## Decision

- Keep one exact home-region `eu-madrid-3` A1 launch path, strict Always Free
  preflight limits, one physical `LaunchInstance` request maximum per run,
  zero SDK retries, idempotency keys, duplicate discovery, and one concurrency
  group.
- Schedule GitHub at minutes `:03, :08, ..., :58` (cron `3-58/5`),
  deliberately avoiding minute zero. Schedule the optional Termux backstop at
  `:00, :05, ..., :55` after explicit operator installation.
- The backstop checks the latest exact-workflow `main` run and skips an
  active run or any completed run created less than four minutes before the
  check. It never blindly POSTs, holds no OCI credentials, and retries no
  ambiguous POST response. The operator must actually reinstall the backstop
  cron block; merging GitHub source alone cannot alter Termux crontab.
- If *any* OCI request returns HTTP 429 or `TooManyRequests`, do not retry
  within the run. Emit `RATE_LIMITED`, request workflow disable, and make
  zero subsequent launch requests. Existing Termux backstop respects the
  inactive workflow. Manual review and deliberate re-enable are required;
  no distributed counter, remote mutable state or self-reenable loop is added.
- A capacity-report 429 must never be silently converted to a 6 GB launch.
  Other report failures retain the approved default 6 GB attempt.
- Per-run structured logs expose status/count for 6/2/1 GB; 1 GB remains
  diagnostic-only because pinned Oracle Linux 9 ARM requires >=2 GB.
- The interval increase is provisional, not proof of greater OCI availability.
  Watch actual run gaps, `RATE_LIMITED`, `CAPACITY_MISS` and `READY`
  results and revert to 15 minutes if service throttling occurs.

## Verification / rollout

The GitHub-hosted regression suite tests schedule-to-backstop alignment,
recency boundary, no duplicate POST while active, OCI preflight/report/launch
429 paths and one-launch-per-run behavior. Complete and merge PR 362 first.
Merge this change only after its tests pass. Update Termux backstop separately
with `termux/install-capacity-cron.sh` after the phone has fast-forwarded to
the reviewed main; verify crontab and `crond` status. No production-device
cron change is implied by a GitHub merge.

## Alternatives

- One-minute GitHub cron: unsupported (minimum five minutes).
- Blind Termux dispatch every five minutes: rejected due to duplicate jobs.
- More than one same-run LaunchInstance attempt: rejected by ADR 0061/0098.
- Stateful remote rate governor or persistent Android OCI client: rejected as
  more complex and harder to secure than fail-closed 429 halt.
