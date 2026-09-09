# ADR 0055: Direct Tailscale SSH operations for the Termux host

- Status: Accepted
- Date: 2026-09-09
- Supersedes: ADR 0015

## Context

The Termux host now has a verified private Tailscale connection from the
operator's Mac and a key-only Termux SSH service supervised by `runit`. The
previous GitHub Actions promotion to a `deploy` branch plus a daily device-side
self-update added a second deployment path without improving this small,
single-device installation.

Android does not make Termux application storage available until the first user
unlock after a reboot. Tailscale and Termux services therefore cannot be
operated remotely before that unlock.

## Decision

- Operate the phone directly over Tailscale SSH using normal Git commands.
- Before changing code, inspect Git state and run relevant tests; commit a
  completed change before it is used in scheduled work.
- Restart only the resident service affected by a change. One-shot cron tasks
  use the changed checkout on their next invocation.
- Remove the GitHub Actions promotion workflow, `deploy` branch update path,
  and daily `deploy.sh` cron task.
- Keep all services private to the tailnet with key-only SSH; expose no public
  inbound port.
- After every device reboot, first unlock Android once and allow the boot hook
  to start services before remote operation.

## Consequences

- The operational path is explicit, small, and recoverable from the Mac.
- No device-side Git fetch, merge, dependency installation, or test suite runs
  on a daily timer.
- The operator must have Tailscale access and perform the first Android unlock
  after a reboot.
- Existing publication and monitoring cron schedules remain independent of
  code deployment.

## Alternatives considered

- GitHub Actions promotion plus a `deploy` branch: rejected as duplicate
  deployment machinery for one privately managed device.
- A resident deployment agent or self-hosted runner: rejected for unnecessary
  runtime and recovery complexity on Termux.
