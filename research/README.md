# Research

This directory holds investigations that support future decisions, especially
data-source evaluation.

Research may be time-sensitive. Keep stable project rules in `docs/kb/` and
durable architecture decisions in `adr/`.

## Community engagement baseline and pilot

- [2026-10-11 — Guardamar community engagement baseline and six-week pilot](2026-10-11-guardamar-community-engagement-baseline-and-pilot.md) — audited comparison of competitor and own Telegram exports; existing pinned guide and manual poll capabilities; corrected data, caveats, proposed measured rollout and deployment boundaries. Research only; not an approved ADR.

## Suggested filename

`YYYY-MM-DD-short-topic.md`

## Research note template

```markdown
# Topic

## Question

What is being evaluated?

## Sources checked

- Owner and URL
- Access date
- Why the source is authoritative

## Findings

- Relevant facts
- Format and update behavior
- Runtime or access constraints

## Recommendation

State the recommendation, confidence, and open questions.
```

Never place credentials, private tokens, or copied secret configuration in a
research note.

