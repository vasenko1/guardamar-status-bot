# 0061: Bounded fail-closed OCI capacity search

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
storage resources. Grant only the low-level mutating permissions required by
the OCI launch matrix: `INSTANCE_CREATE`, `VNIC_CREATE`, `VNIC_ATTACH`, and
`SUBNET_ATTACH`. Do not grant NSG permissions because this launch does not
specify an NSG.

The repository applies stricter gates that OCI IAM cannot express: exact
display name, `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM, fixed subnet, public IPv4,
and the Stack's remaining launch settings. Every possible launch must first
prove there is no non-terminated instance with the target name and that adding
1 OCPU, 6 GB RAM, and a conservatively budgeted 50 GB boot volume stays within
the 2 OCPU, 12 GB RAM, and 200 GB Always Free ceilings. Trial service limits do
not replace these ceilings.

After explicit Phase 2 owner approval, scheduled executions and a deliberately
selected manual launch perform two complete preflight audits and at most one
physical `LaunchInstance` request. The boot volume is pinned to 50 GB to prevent
API-default drift, and two freeform tags supplement—without replacing—name and
full configuration checks. SDK retry is disabled at client and request level.
Capacity and rate-limit responses are not retried in the same run. Ambiguous
responses permit only bounded instance discovery, never another create call.

## Consequences

- Manual dispatch defaults to a read-only audit; scheduled runs may make one
  launch request only after every gate passes.
- Pull requests never receive these OCI secrets because this workflow has no
  pull-request trigger.
- GitHub concurrency prevents overlapping audits, and OCI SDK automatic retries
  are disabled.
- Every run re-audits immediately before the idempotent request. Existing or
  newly accepted targets are verified through RUNNING and public IPv4.
- READY, permanent configuration errors, and unresolved ambiguous results ask
  GitHub to disable the workflow. OCI-state checks remain authoritative if
  disablement fails.
- The first approved production request was rejected by OCI authorization with
  `404 NotAuthorizedOrNotFound`; Audit showed no resource ID and Compute stayed
  empty. The workflow disabled itself and was not retried. Dependent-resource
  `use` verbs conditioned on `request.operation` were replaced by the smaller
  explicit permission set before any future validation attempt.
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
