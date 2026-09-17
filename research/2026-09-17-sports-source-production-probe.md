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

Before wiring FACV/Pesca CV into the guide, run the source modules themselves on
the production device once to confirm that the current raw HTML is parsed by
the deterministic table contracts. This is a parser-shape verification, not a
new recurring runtime requirement.
