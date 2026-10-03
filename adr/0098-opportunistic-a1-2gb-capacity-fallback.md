# 0098: Opportunistic A1 2 GB fallback selected by capacity report

- Status: Accepted
- Date: 2026-10-03
- Related: ADR 0061, ADR 0063, ADR 0097

## Context

The bounded Madrid 3 Always Free hunter has repeatedly reached OCI's real
`LaunchInstance` capacity check for `VM.Standard.A1.Flex` at 1 OCPU / 6 GB
and received `Out of host capacity`.

A production memory probe on the current Termux host observed about 240 MB peak
visible Termux RSS and about 173 MB peak aggregate Python RSS during bounded
preview workloads. Oracle Linux 9 on aarch64 requires at least 2 GB RAM, so
1 OCPU / 2 GB is the smallest acceptable production fallback for the pinned
ARM image.

The dedicated OCI identity was granted only
`COMPUTE_CAPACITY_REPORT_CREATE` through
`manage compute-capacity-reports`. Two live, non-launching capacity reports
proved that 1/6, 1/2 and 1/1 all returned `OUT_OF_HOST_CAPACITY` at the
sampled times. That does not prove the two supported profiles must always have
the same host-capacity result.

## Decision

Keep 1 OCPU / 6 GB as the primary and default launch intent. Add exactly one
fallback intent: the same A1 shape, image, AD, subnet, boot volume, SSH key,
tags and safety controls with RAM reduced to 2 GB.

After the existing two complete OCI-state audits pass and no target exists,
request one fresh Compute Capacity Report containing both approved profiles.
Use 2 GB only when all of the following are true in that one report:

- 1/6 is explicitly `OUT_OF_HOST_CAPACITY`;
- 1/2 is explicitly `AVAILABLE`;
- if OCI supplies `available_count`, it is greater than zero.

Every other report outcome preserves the old 6 GB behavior. This includes
report failure, authorization failure, missing/duplicate rows, unknown status,
both profiles available, both profiles unavailable, or an explicit 2 GB count
of zero. The report is therefore an opportunistic selector, not a mandatory
launch gate.

Each workflow run still makes at most one physical `LaunchInstance` request.
There is no same-run 6 GB → 2 GB retry.

Existing targets are accepted only when their exact RAM is one of the two
approved values, 6 GB or 2 GB. A 1 GB target remains invalid.

The OCI retry token is bound to both `GITHUB_RUN_ID` and selected memory.
A rerun that selects the same profile reuses the same token; a rerun whose
fresh capacity report changes the selected profile gets a distinct token, so
two different launch payloads never share one idempotency key.

## Consequences

- The current 6 GB search loses no attempt when the capacity report is
  unavailable or inconclusive.
- A future narrow host-capacity window that fits 2 GB but not 6 GB can be used
  without adding a second launch request.
- The Always Free ceilings, 50 GB boot volume, exact image/network identity,
  duplicate detection, no-SDK-retry rule, ambiguous-response discovery and
  workflow disable behavior remain unchanged.
- Android still receives no OCI SDK, OCI credential, capacity-report logic or
  launch manifest.
- The Termux backstop remains unchanged because it dispatches the same
  `action=launch` workflow path.
