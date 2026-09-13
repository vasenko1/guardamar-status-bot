# ADR 0063: Termux backstop for the OCI capacity schedule

- Status: Accepted
- Date: 2026-09-13
- Complements: ADR 0061

## Context

GitHub's scheduled workflow event is best-effort and can arrive late or be
missed. The existing OCI capacity workflow already has one concurrency group,
two complete preflight audits and at most one non-retried launch request per
run. A second blind scheduler would generate unnecessary duplicate runs.

## Decision

- Keep the OCI SDK, OCI identity, private key, launch manifest, audit and
  `LaunchInstance` entirely on GitHub-hosted runners. Android never calls OCI.
- Keep the GitHub schedule at minutes 7, 22, 37 and 52 as the first attempt.
  An optional Termux one-shot backstop checks at minutes 12, 27, 42 and 57.
- Use a fine-grained GitHub PAT limited to `vasenko1/guardamar-status-bot` and
  repository Actions read/write. Store it only in the private Termux token
  file, not in `.env`, source control, process arguments or logs.
- Read exact workflow metadata and its latest `main` run through bounded,
  single-attempt GitHub API requests. Do nothing when the workflow is inactive,
  either read is uncertain, the latest run is queued/in progress, or its
  `created_at` is less than ten minutes old.
- Otherwise send exactly one `workflow_dispatch` with `action=launch`. Never
  repeat that POST in the same invocation, including after an ambiguous
  response. No persistent stop-marker or phone-side OCI result polling exists.
- Share the existing project runtime lock and retain only a bounded current
  and previous backstop log. The cron installer changes only its own block.

## Consequences

The phone adds only outbound, standard-library GitHub metadata reads and an
occasional dispatch. It stores no OCI credential or SDK and cannot itself
create a VM. A rare GitHub scheduled event arriving after the Termux check can
still produce two workflow runs; the existing workflow concurrency and OCI
duplicate/preflight gates remain the final protection. When the workflow's
existing disable step succeeds after `READY` or an unsafe OCI outcome, future
Termux checks exit without POST. If disablement fails, OCI's existing target
and preflight gates still prevent an extra launch. The operator separately
removes the optional cron block when capacity hunting is no longer needed.

## Alternatives considered

- Blind phone dispatch every 15 minutes: rejected because it systematically
  duplicates normal GitHub scheduled runs.
- OCI client or private key on Android: rejected because it weakens the
  GitHub-only execution boundary.
- Daemon, wake lock, GitHub App, or distributed lock: rejected as unnecessary
  complexity for this bounded fallback.
