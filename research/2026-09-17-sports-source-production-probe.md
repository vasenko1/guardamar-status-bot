# Sports source production probe — 2026-09-17

Production device: Android / Termux used by `guardamar-status-bot`.

The operator ran one read-only standard-library `urllib` probe with redirects
disabled, a 15-second timeout and a 1 MiB+1 read cap.

| Source | Status | MIME | Bytes read | Final URL unchanged | Time | `guardamar` count |
| --- | ---: | --- | ---: | --- | ---: | ---: |
| FACV | 200 | `text/html` | 637691 | yes | 0.514 s | 37 |
| Federación Pesca CV | 200 | `text/html` | 1037513 | yes | 3.402 s | 50 |
| ChipLevante | 200 | `text/html` | 169756 | yes | 1.034 s | 0 |
| RFET | 200 | `text/html` | 96847 | yes | 1.768 s | 6 |

## Decision

- FACV transport contract is accepted for a bounded source adapter.
- Federación Pesca CV transport contract is accepted for a bounded source
  adapter. Its current payload is already about 1.04 MB, so the implementation
  uses a 1.5 MiB response limit and exactly one source read in the existing
  daily guide observation; no event-detail requests or inner retry loop.
- ChipLevante is production-reachable but still has no current future Guardamar
  row. Keep it as a candidate, not implemented code.
- RFET is production-reachable but remains deferred because the currently
  demonstrated resident value is one annual Guardamar Open.

## Parser-shape verification on the production device

The source modules themselves were then executed against the live HTML from the
same Android / Termux runtime.

FACV parsed successfully and returned an empty future Guardamar event set on
2026-09-17. This is expected because the Guardamar chess events visible in the
2026 FACV calendar before this date had already ended.

Federación Pesca CV parsed successfully and returned two eligible future rows
after the strict level filter:

- `PROVINCIAL — MAR COSTA`, 17 October 2026, `ZONA B - CENTRO, LA ROQUETA Y MONCAYO`;
- `NACIONAL — MAR COSTA DÚOS`, 23–29 November 2026, `PLAYA`.

The live parser result corrected the earlier manual audit: `MAR COSTA DÚOS`
also has a row on 29 November, so the supported range is 23–29 November, not
23–28 November.

This completes the production transport and parser-shape acceptance for FACV
and Federación Pesca CV. No further production source probe is required before
running the normal test suite and previewing the guide integration.
