# OCI Capacity Automation

This off-device automation makes at most one bounded attempt per run to create
the Resource Manager Stack-derived `guardamar-bot` target within strict OCI
Always Free ceilings. Phase 2 was explicitly approved on 2026-09-11.

## Dedicated identity

- User: `guardamar-capacity-bot`
- Group: `guardamar-capacity-automation`
- Policy: `guardamar-capacity-automation-policy`
- GitHub secret names: `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`,
  and `OCI_PRIVATE_KEY`

The exact active policy is:

```text
Allow group Default/guardamar-capacity-automation to read instances in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to {INSTANCE_CREATE} in tenancy where all {request.region = 'eu-madrid-3', request.ad = 'OhIQ:EU-MADRID-3-AD-1', target.image.id = 'ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko55bl6tfkqjk472gvvl6yq'}
Allow group Default/guardamar-capacity-automation to read instance-images in tenancy where all {request.region = 'eu-madrid-3', target.image.id = 'ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko55bl6tfkqjk472gvvl6yq'}
Allow group Default/guardamar-capacity-automation to {VNIC_CREATE, VNIC_ATTACH} in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to {SUBNET_ATTACH} in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to inspect vnic-attachments in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to inspect vnics in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to inspect subnets in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to read resource-availability in tenancy
Allow group Default/guardamar-capacity-automation to read app-catalog-listing in tenancy where request.region = 'eu-madrid-3'
```

The mutating permissions are the exact low-level set required by the OCI
`LaunchInstance` permission matrix: `INSTANCE_CREATE`, `VNIC_CREATE`,
`VNIC_ATTACH`, and `SUBNET_ATTACH`. The first production request showed that
conditioning dependent resource verbs on `request.operation` did not authorize
the compound launch consistently, so those verbs were replaced by their
smaller permission sets. The identity has no `INSTANCE_DELETE`,
`INSTANCE_UPDATE`, `INSTANCE_POWER_ACTIONS`, `VNIC_DELETE`, `VNIC_UPDATE`, or
`SUBNET_DETACH`; it has no NSG permission and no create, update, or delete
permission for subnet, VCN, block volume, or boot volume resources.

## First production attempt

The explicitly approved first production dispatch ran on 2026-09-11. Both
preflights passed and the process made exactly one SDK `LaunchInstance` call.
OCI returned `404 NotAuthorizedOrNotFound`. OCI Audit recorded only
`LaunchInstance.begin`, with `resourceId` null, and the Compute instance list
remained empty. The workflow then disabled itself as designed. No same-run or
follow-up launch was attempted.

The active policy was subsequently narrowed to the exact permissions above.
The workflow remains disabled until a separately approved validation attempt;
neither a schedule nor a manual dispatch can launch while it is disabled.

## Execution gates

Scheduled runs and an explicitly selected manual `launch` execute:

```text
python -m automation.guardamar_capacity launch --allow-launch
```

The command still requires the compiled Phase 2 gate and the exact workflow
switch. Before its single SDK request it performs two complete OCI-state audits.
It identifies a target by display name or either of two freeform tags, and any
non-terminated target causes zero launch calls. OCI SDK automatic retries are
disabled at both client and request level.

`Out of host capacity` and HTTP 429 end the current run without retry. An
ambiguous response starts only bounded read-after-write discovery; it never
repeats `LaunchInstance`. A permanent rejection or unresolved ambiguous result
requests workflow disablement. An accepted or previously discovered instance
is polled conservatively and must match image, shape, OCPU, RAM, AD, subnet, and
public IPv4 before the result becomes `READY`.

Manual dispatch defaults to `audit`; `launch` must be deliberately selected.
The workflow has one concurrency group and runs at minutes 7, 22, 37, and 52.
After `READY` it asks GitHub to disable this workflow. If that request fails,
future runs still find the OCI instance and make zero launch calls.
