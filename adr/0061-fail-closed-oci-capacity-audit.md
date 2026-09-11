# 0061: Fail-closed OCI capacity audit before any VM launch

- Status: Accepted
- Date: 2026-09-11

## Context

The OCI Resource Manager Stack contains an unsuccessful manual definition of
one `guardamar-bot` A1 instance. Repeated applies failed because the selected
availability domain had no host capacity. A bounded off-device check can
inspect capacity later, but credentials in GitHub must not be sufficient to
cause an unapproved or non-free launch.

## Decision

Keep the automation separate from the Termux application and run a short
GitHub Actions audit at minutes 7, 22, 37, and 52. It uses a dedicated OCI API
identity whose policy can read only the relevant state and submit
`LaunchInstance` only for the fixed Madrid region, AD, and image. It cannot
terminate, update, or power instances and cannot modify existing network or
storage resources. Subnet, VNIC, and network-security-group `use` permissions
are each restricted to the `LaunchInstance` operation.

The repository applies stricter gates that OCI IAM cannot express: exact
display name, `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM, fixed subnet, public IPv4,
and the Stack's remaining launch settings. Every possible launch must first
prove there is no non-terminated instance with the target name and that adding
1 OCPU, 6 GB RAM, and a conservatively budgeted 50 GB boot volume stays within
the 2 OCPU, 12 GB RAM, and 200 GB Always Free ceilings. Trial service limits do
not replace these ceilings.

In this accepted revision the workflow executes only `audit`; the launch
command is also guarded by a committed build-time false constant before it
loads credentials. Enabling it requires a later owner-authorized code change.
No retry loop, Terraform apply, Resource Manager mutation, Telegram credential,
or Telegram delivery is part of this phase.

## Consequences

- A schedule or manual dispatch in this revision performs read-only OCI calls.
- Pull requests never receive these OCI secrets because this workflow has no
  pull-request trigger.
- GitHub concurrency prevents overlapping audits, and OCI SDK automatic retries
  are disabled.
- A future launch-enabling change must retain the duplicate and free-tier gates,
  re-audit immediately before one idempotent request, and receive separate
  explicit owner approval.
- The OCI policy cannot constrain shape, display name, or subnet on
  `LaunchInstance`; repository gates and the immutable launch manifest cover
  those fields.

## Alternatives considered

- Re-running Terraform Apply: rejected because it couples polling to broader
  Stack behavior and previously produced repeated failed jobs.
- Giving the automation broad Compute or Administrator rights: rejected because
  delete, update, power, network, and storage mutation are outside scope.
- Using the trial's larger limits as cost gates: rejected because they do not
  prove that a launch remains within Always Free allowances.
