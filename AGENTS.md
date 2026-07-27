# Instructions for AI Agents

This file is the main entry point for AI-assisted work in this repository.

## Required reading

Before making any change, read these files in order:

1. `docs/kb/00_Project_Overview.md`
2. `docs/kb/01_Product_Vision.md`
3. `docs/kb/02_Project_Principles.md`
4. `docs/kb/03_System_Architecture.md`
5. `docs/kb/04_Runtime_Constraints.md`

Then read any other knowledge-base, research, or ADR files relevant to the
task.

## Working rules

- Keep the bot lightweight and suitable for Termux on a weak Android device.
- Do not break the documented runtime constraints.
- Prefer official, authoritative sources over aggregators or scraped copies.
- Add dependencies only when their value clearly exceeds their runtime cost.
- Keep modules and changes small, explicit, and easy to recover after failure.
- Do not invent missing facts, source data, requirements, or user-facing
  claims.
- Do not implement the undefined future feature until its scope is approved.
- Update the knowledge base after important product or architecture decisions.
- Record durable architecture choices in `adr/` and summarize them in
  `docs/kb/10_Decision_Log.md`.
- Put time-sensitive source investigations in `research/`, not in the stable
  knowledge base.

## Change discipline

- Stay within the requested scope.
- Preserve simple boundaries between collection, normalization, digest
  building, and delivery.
- Add or update tests when application behavior is introduced or changed.
- Keep secrets, tokens, local state, and generated runtime data out of
  documentation and source control.

