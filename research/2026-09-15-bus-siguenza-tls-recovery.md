# Bus Sigüenza TLS recovery check — 2026-09-15

## Production symptom

On the Termux host, the transport-notification baseline repeatedly logged:

`Tomorrow airport timetable unavailable; exact airport change detection will skip the next day rather than guess: TLS intermediate is unavailable`

The accepted current airport snapshot and fare remained usable, but the
next-day baseline could not be collected.

## Cause

ADR 0043's recovery derived the leaf CA Issuers AIA and rewrote the official
HTTP `*.i.lencr.org` address to HTTPS. The current recovery request itself is
therefore the failing step. The AIA host is useful as an issuer identifier, but
it is not necessary to use it as the certificate download endpoint.

Let's Encrypt documents `i.lencr.org` as its issuer-certificate namespace and,
as of its Chains of Trust page updated 2026-07-08, lists YE1, YE2, YR1 and YR2
as the active intermediates, YE3/YR3 as backups, and E5-E9/R10-R14 as retired
but still-valid prior intermediates. The same official page links DER copies
under `https://letsencrypt.org/certs/`; current DER responses use
`application/x-x509-cert`.

## Recovery boundary

Use the leaf AIA only to select one reviewed issuer label, fetch only the
corresponding fixed official HTTPS certificate path(s), keep normal system
trust and hostname verification, and fail closed for every unknown label or
unexpected response. Generation Y needs the intermediate plus its official
cross-signed Root YE/Root YR certificate; the earlier 2024 intermediates need
only their intermediate because ISRG Root X1/X2 is already the system trust
anchor.

Official references reviewed:

- https://letsencrypt.org/docs/lencr.org/
- https://letsencrypt.org/certificates/
- https://letsencrypt.org/2025/11/24/gen-y-hierarchy/
