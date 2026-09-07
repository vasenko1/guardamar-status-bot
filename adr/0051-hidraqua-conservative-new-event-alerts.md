# ADR 0048: Hidraqua conservative new-event alerts

- Status: Accepted
- Date: 2026-09-08

## Decision

Run one externally scheduled, one-shot `monitor-hidraqua` command every ten
minutes. It reads only active `4AP`/`5EC` Guardamar rows and sends one notice
only for each new `CI_ID`. The first successful read is a quiet bootstrap;
changed and disappeared rows are silent. State is atomic and retains IDs for
180 days.

The official map proves water-network works/affectations but not a guaranteed
outage at every address. Public wording therefore reports an accident or
improvement work on the water network, never that water is definitely off.

## Consequences

- Multiple concurrent IDs produce one notice each.
- No token, browser automation, resident process, raw storage, or dependency.
