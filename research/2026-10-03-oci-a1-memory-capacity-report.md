# OCI A1 memory-profile capacity report — 2026-10-03

## Question

Does reducing the existing Always Free `VM.Standard.A1.Flex` target from
1 OCPU / 6 GB to 1 OCPU / 2 GB materially expose host capacity in
`eu-madrid-3`, and is a 1 GB fallback worth considering?

## Official basis

Oracle documents Compute Capacity Reports as a pre-launch view of host capacity
inside one availability domain. A single report accepts a list of shape
availability requests, including Flex shape `ocpus` and `memory_in_gbs`,
and returns `availability_status` plus `available_count` for each requested
configuration.

The IAM resource type `compute-capacity-reports` exposes only one permission
under `manage`: `COMPUTE_CAPACITY_REPORT_CREATE`.

Oracle Linux 9 minimum required memory on aarch64 is 2 GB.

Sources:

- https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/compute/compute-capacity-report/create.html
- https://docs.oracle.com/en-us/iaas/tools/python/latest/api/core/models/oci.core.models.CapacityReportShapeAvailability.html
- https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/corepolicyreference.htm
- https://docs.oracle.com/en/operating-systems/oracle-linux/limits/

## Live probe

The operator added:

`Allow group Default/guardamar-capacity-automation to manage compute-capacity-reports in tenancy`

The first one-shot GitHub probe, run `37153659434`, made exactly one
`CreateComputeCapacityReport` call for two configurations:

```json
[
  {"shape": "VM.Standard.A1.Flex", "ocpus": 1.0, "memory_in_gbs": 6.0,
   "availability_status": "OUT_OF_HOST_CAPACITY", "available_count": null},
  {"shape": "VM.Standard.A1.Flex", "ocpus": 1.0, "memory_in_gbs": 2.0,
   "availability_status": "OUT_OF_HOST_CAPACITY", "available_count": null}
]
```

A second one-shot probe, run `37153752550`, repeated those profiles and added
1 OCPU / 1 GB. All three returned `OUT_OF_HOST_CAPACITY` with
`available_count=null`.

Neither probe called `LaunchInstance`.

## Interpretation

The live result does not prove that 2 GB can never become available while 6 GB
is unavailable. It proves only that reducing memory did not create an available
path at either sampled moment. The current shortage therefore appears broader
than a simple 6 GB memory-fit problem.

The 1 GB profile is rejected independently because the pinned Oracle Linux 9
aarch64 operating system requires at least 2 GB RAM.

ADR 0098 implements the capacity report as an opportunistic selector. The
primary remains 1 OCPU / 6 GB. The 2 GB fallback is selected only when one
fresh report explicitly returns 6 GB `OUT_OF_HOST_CAPACITY` and 2 GB
`AVAILABLE`, with a positive count when OCI supplies one. Failure, missing or
unexpected report data and every other status combination preserve the old
6 GB launch behavior.

The selector does not add a second `LaunchInstance` request. Its retry token
also includes the selected memory so a GitHub rerun that changes profile cannot
reuse an idempotency key for a different payload.

The implementation passed compile validation and 42 focused
capacity/backstop tests in GitHub Actions run `37154248312` before activation.
