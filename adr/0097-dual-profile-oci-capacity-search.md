# 0097: Dual-profile OCI Always Free capacity search

- Status: Accepted
- Date: 2026-10-03
- Extends: ADR 0061 and ADR 0063

## Context

The bounded OCI hunter has reached the real `LaunchInstance` capacity check
for `VM.Standard.A1.Flex` since 2026-09-12, but repeated Madrid 3 attempts
continue to return `Out of host capacity`. Oracle still documents a separate
Always Free AMD option, `VM.Standard.E2.1.Micro`, with up to two instances.
It uses a different shape and x86_64 image, so it can provide an independent
capacity path without abandoning the existing A1 search.

## Decision

Keep one GitHub workflow, one concurrency group, the existing dedicated OCI
identity and the existing duplicate target identity. Define two immutable
profiles:

- `a1`: `VM.Standard.A1.Flex`, 1 OCPU, 6 GB RAM, the existing Oracle Linux
  9.8 aarch64 image.
- `e2`: `VM.Standard.E2.1.Micro`, fixed shape, Oracle Linux 9.8 x86_64
  image `ocid1.image.oc1.eu-madrid-3.aaaaaaaa2nsuyzwg7zpslg3xvd4xbt2jlrbsicyie7uipj2pbhrcryudgjga`.

Scheduled and automatic backstop launches select `auto` and alternate profiles
by GitHub workflow run number. A manual dispatch may force either profile.
Manual audit keeps A1 as the compatibility default when `auto` is selected.

Every run still makes at most one physical `LaunchInstance` request. It never
tries A1 and E2 in the same run. Before any profile-specific image, shape or
limit read, it first checks for an existing target by the shared display
name/tags. Any non-terminated target therefore turns every later run into a
zero-create verifier regardless of which profile would otherwise be selected.

The A1 cost gates remain 2 Always Free OCPUs, 12 GB Always Free RAM and the
shared 200 GB Always Free block-storage ceiling. E2 uses Oracle's
availability-domain-scoped `standard-e2-micro-core-count` service limit and
the same shared storage ceiling. Both profiles pin a 50 GB boot volume and the
same Madrid 3 AD, subnet, public IPv4 requirement, SSH key, tags and launch
safety controls. Because E2 is fixed, the request deliberately omits the A1
`shape_config`.

The automation identity remains least-privilege. Activating E2 requires one
additional exact-image `INSTANCE_IMAGE_READ` grant for the x86_64 image; it
does not receive broad image-read or IAM-management permissions.

## Activation gate

Do not merge this change into the active scheduled workflow until the exact
E2 image-read policy is present and a manual E2 read-only audit succeeds.
A failed E2 audit is safe because manual audit cannot request workflow
disablement. After activation, any permanent launch rejection remains
fail-closed and requests workflow disablement as before.

## Consequences

- A1 capacity hunting continues instead of being replaced.
- E2 receives roughly half of automatic attempts without doubling the number
  of OCI create requests.
- The Termux backstop remains compatible because the new profile input is
  optional and defaults to `auto`.
- A successful A1 or E2 instance stops creation for both profiles.
- The phone still carries no OCI SDK, credential, manifest or audit logic.
- E2's 1 GB RAM is accepted only as an infrastructure fallback; application
  suitability is evaluated separately after a VM is actually obtained.
