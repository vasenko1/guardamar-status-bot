# 0066: Recover Bus Sigüenza TLS from the official Let's Encrypt repository

- Status: Accepted
- Date: 2026-09-15
- Supersedes: the TLS-recovery portion of ADR 0043

## Context

Bus Sigüenza still omits the issuing chain on the production host. The original
recovery read the leaf AIA and changed its `http://<issuer>.i.lencr.org/` URL to
HTTPS. In September 2026 that path fails on Termux with `TLS intermediate is
unavailable`. Let's Encrypt's current Chains of Trust page publishes the active
Generation Y intermediates (YE1/YE2 and YR1/YR2), their backup YE3/YR3
intermediates, the cross-signed Generation Y roots, and the still-valid 2024
E5-E9/R10-R14 intermediates through its official HTTPS certificate repository.
The repository serves DER files as `application/x-x509-cert`.

## Decision

For the existing missing-issuer-only recovery on exactly
`www.bus-siguenza.com`:

1. Read the unverified leaf only to obtain its single CA Issuers AIA label.
2. Accept only the known Let's Encrypt labels YE1-YE3, YR1-YR3, E5-E9 and
   R10-R14 on the exact `*.i.lencr.org/` AIA form. The AIA URL itself is never
   fetched and never becomes a trust source.
3. Map that label to fixed paths under `https://letsencrypt.org/certs/`.
4. For Generation Y, also load the corresponding official cross-signed Root YE
   or Root YR certificate so the chain reaches the system-trusted ISRG root.
5. Accept only exact allowlisted HTTPS paths, no credentials/query/fragment, a
   200 response, the exact requested final URL, DER certificate MIME
   (`application/x-x509-cert` or `application/pkix-cert`), and the existing
   16 KiB certificate size bound.
6. Build a fresh default SSL context, add the one- or two-certificate recovery
   chain in memory, and retry the original Bus Sigüenza request with normal
   hostname and certificate verification still enabled.
7. Cache that verified context only in memory for the one-shot process. Store no
   certificate bytes and do not enter this path for any TLS error except a
   missing issuer.

## Consequences

- The recovery no longer depends on HTTPS support at `*.i.lencr.org`.
- Current Generation Y issuance is supported without trusting the new Y roots
  directly: the official cross-signed root connects to ISRG Root X1 or X2 in
  the normal system trust store.
- A future unknown intermediate fails closed until its official repository path
  is reviewed and allowlisted.
- Normal successful TLS requests make no additional request. A broken-chain
  process makes at most two small official certificate reads and reuses the
  repaired context for the remaining one-shot work.
- No dependency, daemon, persisted certificate, disabled verification, or
  generic certificate downloader is added.
