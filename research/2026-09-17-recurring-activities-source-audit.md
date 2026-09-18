# Guardamar recurring activities source audit — 2026-09-17

> **Status: superseded for current planning.**
>
> The synchronized source of truth is
> `research/2026-09-17-recurring-activities-and-language-sources.md`.
> This older audit is retained only as a record of the earlier investigation.
> Do not use its implementation sequence or deferred/ready classifications when
> they conflict with the synchronized document.

## What changed after this audit

The later investigation corrected or extended several conclusions:

- FACV/Pesca federation event work is already implemented, tested, merged and
  deployed; it is no longer a prerequisite for recurring-activity work.
- Tertulia Literaria has a durable official static page with an explicit weekly
  schedule, so it is a recurring-card candidate rather than merely a monitored
  agenda item.
- the language investigation expanded substantially: EPA Spanish, EPA
  English/Valencian, EOI Guardamar, Cruz Roja, PANGEA, INTEGRA, Educare and
  Kairós now have separate evidence/status;
- EOI Guardamar is an official physical section of EOI Torrevieja in Guardamar,
  not merely an uncertain Torrevieja option;
- PANGEA and INTEGRA must remain separate programmes;
- unattended operation means slow/static sources should use cheap
  low-frequency automatic revalidation rather than depend on manual seasonal
  checks;
- the current preferred cost model is zero-extra-GET reuse where possible,
  one small municipal discovery request, and changed-detail/form reads only
  when a fingerprint changes.

## Still-valid architectural constraints

The following principles from the original audit remain current:

- recurring activities belong in the linked `🎓 Занятия и секции` guide, not
  the one-off Event pipeline;
- no generic recurring-activity framework, provider registry, YAML layer,
  database, browser, LLM parser, daemon or per-source cron;
- source-specific deterministic parsers are preferred;
- source failure preserves last-good facts;
- deleted-card recovery and relinking are mandatory;
- semantic resident-facing changes may notify; raw HTML churn/source failure do
  not;
- never invent current schedule, price, availability or season from old data.

## Current next step

Before recurring-card production code is written, complete the single read-only
production transport probe documented in the synchronized research file. It
will choose the smaller stable Ayuntamiento discovery contract (REST vs RSS)
and verify the static sources from the actual Termux network.

After that, the intended implementation sequence is currently:

1. Chess + Tertulia;
2. creative workshops from the already-fetched Turismo page;
3. Dinamización Social;
4. language cards only when their exact current machine source contracts are
   sufficient.
