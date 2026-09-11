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
Allow group Default/guardamar-capacity-automation to manage instances in tenancy where all {request.operation = 'LaunchInstance', request.permission = 'INSTANCE_CREATE', request.region = 'eu-madrid-3', request.ad = 'OhIQ:EU-MADRID-3-AD-1', target.image.id = 'ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko55bl6tfkqjk472gvvl6yq'}
Allow group Default/guardamar-capacity-automation to read instance-images in tenancy where all {request.region = 'eu-madrid-3', target.image.id = 'ocid1.image.oc1.eu-madrid-3.aaaaaaaaurntbnbuaaicth3wbgs77lkqcb6giko55bl6tfkqjk472gvvl6yq'}
Allow group Default/guardamar-capacity-automation to use vnics in tenancy where all {request.operation = 'LaunchInstance', request.region = 'eu-madrid-3'}
Allow group Default/guardamar-capacity-automation to use subnets in tenancy where all {request.operation = 'LaunchInstance', request.region = 'eu-madrid-3'}
Allow group Default/guardamar-capacity-automation to inspect vnic-attachments in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to inspect vnics in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to inspect volumes in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to read resource-availability in tenancy
Allow group Default/guardamar-capacity-automation to use network-security-groups in tenancy where all {request.operation = 'LaunchInstance', request.region = 'eu-madrid-3'}
Allow group Default/guardamar-capacity-automation to inspect subnets in tenancy where request.region = 'eu-madrid-3'
Allow group Default/guardamar-capacity-automation to read app-catalog-listing in tenancy where all {request.operation = 'LaunchInstance', request.region = 'eu-madrid-3'}
```

The broad-looking `manage instances` verb is narrowed to only the
`INSTANCE_CREATE` permission of `LaunchInstance`, in the exact region, AD, and
image. The identity has no `INSTANCE_DELETE`, `INSTANCE_UPDATE`, or
`INSTANCE_POWER_ACTIONS`; it also has no create, update, or delete permission
for subnet, VCN, NSG, block volume, or boot volume resources.

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
