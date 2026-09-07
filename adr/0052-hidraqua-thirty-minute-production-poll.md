# ADR 0052: Hidraqua thirty-minute production poll

- Status: Accepted
- Date: 2026-09-08

## Decision

Use the existing Termux cron / one-shot pattern for Hidraqua. The idempotent
`termux/install-hidraqua-cron.sh` installs exactly one `*/30 * * * *` entry
for `termux/monitor-hidraqua.sh`; it preserves unrelated crontab rows and
starts the existing `crond` service.

The first production invocation keeps `HIDRAQUA_PUBLISH_CURRENT_ON_BOOTSTRAP`
unset, so active source IDs become a quiet local baseline.

## Consequences

- No resident Hidraqua process or duplicate scheduler is introduced.
- `state/hidraqua.json` remains the persistent shared state for manual and
  cron invocations.
- Android reboot recovery remains governed by the existing Termux/Termux:Boot
  setup; this installer does not install or alter Android boot services.
