# 0097: Reject dual-profile OCI A1 + E2 capacity search

- Status: Rejected
- Date: 2026-10-03
- Related: ADR 0061 and ADR 0063

## Context

The existing bounded hunter reaches the real OCI host-capacity check for the
Always Free `VM.Standard.A1.Flex` target in `eu-madrid-3`, but repeated
attempts return `Out of host capacity`. Oracle's general Always Free
documentation also lists up to two `VM.Standard.E2.1.Micro` instances, so an
E2 fallback was investigated as a separate free compute path.

## Investigation

The operator temporarily granted the dedicated automation identity read access
to one exact Oracle Linux 9.8 x86_64 image. A GitHub-hosted read-only audit
then proved:

- the x86_64 image is readable;
- the existing subnet is readable and can provide a public VNIC;
- the E2 service-limit record is readable and reports zero usage;
- free-storage usage is zero;
- no target instance exists;
- `VM.Standard.E2.1.Micro` is not returned for the configured image and AD.

A second read-only `ListShapes` probe removed the image filter entirely. OCI
still returned no E2-family shapes at all for
`OhIQ:EU-MADRID-3-AD-1`. Oracle documents `eu-madrid-3` as a one-AD region,
so there is no alternate AD to try inside the tenancy's home region.

No E2 `LaunchInstance` request was made.

## Decision

Do not activate an E2 profile in the capacity hunter. Restore the production
code and workflow to the original A1-only design from ADR 0061/0063 and remove
the temporary read-only audit workflow.

The temporary exact x86 image-read IAM statement is no longer needed and should
be removed from OCI Console to restore least privilege.

## Consequences

- Production capacity hunting remains unchanged: A1 1 OCPU / 6 GB only.
- No extra create attempts, schedules, credentials or Android runtime work are
  added.
- The E2 result remains in research so the same unavailable path is not
  reimplemented without new evidence that Madrid 3 exposes the shape.
