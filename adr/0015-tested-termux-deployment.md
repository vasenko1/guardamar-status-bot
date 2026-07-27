# ADR 0015: Tested Termux deployment

## Status

Accepted and implemented

## Context

The production bot runs on an Android phone behind a normal consumer network.
GitHub cannot safely initiate an inbound connection to it. A self-hosted
GitHub Actions runner would add a privileged resident process, memory use, and
maintenance burden to a weak device.

## Decision

- Run the complete test suite in GitHub Actions for every push and pull
  request.
- After a successful push to `main`, fast-forward the repository's `deploy`
  branch to that exact tested commit.
- Let Termux check `deploy` once daily at 06:45, before the 07:30 digest.
- Accept only a clean working tree and a fast-forward update.
- Install declared Python dependencies and rerun the tests on the phone.
- Restore the previous commit if installation or device tests fail.
- Restart only the optional preview listener after a successful update. The
  one-shot morning process will naturally use the new files at its next run.
- Keep `.env`, runtime state, logs, and the virtual environment outside Git.

## Consequences

The phone needs no inbound port, GitHub secret, webhook, VPN, or resident
deployment runner. Deployment may occur up to one day after merge, which is
acceptable for a once-daily product and materially reduces idle work.

Direct tracked-file edits on the phone intentionally block deployment until
the operator reviews them. A rewritten or divergent Git history also fails
closed instead of overwriting the device.

## Alternatives rejected

- Self-hosted GitHub Actions runner: too heavy and privileged for the target
  device.
- SSH from GitHub: requires externally reachable infrastructure and secret
  management.
- Pull directly from `main`: the phone could receive a commit before its CI
  result is known.
- Frequent polling: unnecessary network and battery use.
