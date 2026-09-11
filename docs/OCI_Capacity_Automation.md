# OCI Capacity Automation

This off-device automation audits whether the Resource Manager Stack-derived
`guardamar-bot` target would fit the strict OCI Always Free ceilings. The
current GitHub workflow is intentionally audit-only. It must not be enabled for
launch without a separate explicit owner approval and a reviewed code change.

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
```

The broad-looking `manage instances` verb is narrowed to only the
`INSTANCE_CREATE` permission of `LaunchInstance`, in the exact region, AD, and
image. The identity has no `INSTANCE_DELETE`, `INSTANCE_UPDATE`, or
`INSTANCE_POWER_ACTIONS`; it also has no create, update, or delete permission
for subnet, VCN, NSG, block volume, or boot volume resources.

## Current lock

`.github/workflows/guardamar-capacity.yml` runs only:

```text
python -m automation.guardamar_capacity audit
```

The Python launch command also checks a committed `LAUNCH_BUILD_ENABLED =
False` before constructing the OCI client. Merely setting an environment value,
manually dispatching the workflow, merging this revision, or waiting for the
schedule therefore cannot submit `LaunchInstance`.

## Revalidation before a future enablement

After explicit owner approval, a later change must keep all existing tests and
must re-check the exact active policy, target inventory, image, shape, A1 OCPU,
A1 RAM, and storage usage. It must preserve GitHub concurrency, the final
immediate re-audit, a stable OCI retry token for one workflow attempt, and a
single SDK request with automatic retries disabled.
