# ADR 0083: On-demand category-first supermarket product awards

- Status: Accepted
- Date: 2026-09-27

## Context

The product-award idea has converged on a strict editorial rule: one exceptional
product from a broad consumer category, published at most once every three local
calendar days, and only when the exact awarded product is currently available
in one of six relevant Spanish supermarket chains.

The earlier proof of concept grew around a different problem: continuously
discovering new award items and placing them into a shared queue. It therefore
accumulated a discovery cron, per-source baselines, seen-item state, a queue and
a reviewed starter seed. The final category-first model does not need those
mechanisms.

The target device is a weak Android phone running Termux alongside many other
one-shot city-information jobs. Network, CPU, memory, dependencies and recovery
complexity must stay small.

## Decision

### 1. Use one on-demand one-shot workflow

Product awards use one short-lived scheduled command. There is no resident
worker and no separate discovery job.

The command reads state first. If fewer than three local calendar days have
passed since the last confirmed product-award publication, it exits successfully
without making award or retailer network requests.

When publication is due, the same invocation selects, verifies, renders and
delivers at most one product.

### 2. Keep a reviewed category registry

Production contains a small explicit registry of broad consumer categories.

Each category defines an ordered list of approved authoritative sources. A
source adapter returns only that source's explicit ordered candidates:

- at most #1, #2 and #3 when a real ordered podium exists;
- only #1 when the authority publishes one winner;
- no inferred ranks from finalists, medal groups, alphabetical lists or tied
  tiers unless the source itself defines an order.

Production does not search the web for new competitions. New award families are
added only after a dated source investigation.

### 3. Exhaust one source before falling back to the next

For one category:

1. load source #1;
2. test its #1 exact product against the supported retailer set;
3. if unavailable or unprovable, test #2, then #3 when explicitly ranked;
4. only when source #1 has no eligible top-three retail match, load source #2
   and restart at that source's #1.

Ranks from different competitions are never merged or compared.

### 4. Retail verification happens after award selection

The supported retailer set is exactly:

- Mercadona;
- Carrefour España supermarket;
- ALDI España;
- Lidl España;
- DIA España;
- Consum.

Retail lookups are candidate-targeted. The bot never crawls a full supermarket
catalogue merely to look for award winners.

Exact retail identity is accepted, in descending strength, by:

1. exact EAN/GTIN;
2. exact retailer SKU/product ID authoritatively tied to the awarded product;
3. exact commercial identity with every category-critical qualifier and no
   competing same-name SKU.

Brand, producer or normalized-name equality alone is insufficient.

Wine must preserve material qualifiers such as label/cuvée, vintage,
designation and bottle size when the award is tied to them. Other categories use
similarly strict variant qualifiers.

### 5. Current price is mandatory and refreshed in the due run

A public post requires one freshly verified exact retail offer from an official
retailer source.

The current price and package are read in the same due invocation, immediately
before rendering. A stale award-page price is not presented as the current
supermarket price.

If exact identity, current availability or price cannot be proven, that
candidate fails closed and selection continues. An unpublishable candidate does
not consume the three-day slot.

### 6. Use small retailer adapters only where a cheap contract is proven

Retail adapters may use bounded official HTML, JSON or embedded application data
with pinned hosts, timeouts, size limits and deterministic validation.

Do not add:

- Chromium, Playwright or another browser runtime;
- OCR;
- search-engine product discovery;
- fuzzy product matching;
- LLM product matching or editorial generation;
- a generic supermarket-crawling framework.

If one retailer cannot be verified cheaply, the candidate is skipped rather
than making the phone architecture heavier.

### 7. Keep state minimal

The workflow needs only a small atomic JSON state containing:

- schema version;
- last confirmed delivery day;
- published category/edition/event identities needed for deduplication;
- a small category cursor or last published category for fair rotation;
- an uncertain delivery reservation when Telegram send outcome is ambiguous.

There is no discovery queue, source baseline, seen-item ledger or cached raw
award/retailer payload.

Before a non-idempotent Telegram send, reserve the event as uncertain. Confirmed
delivery records it as published. Explicit deterministic send failure clears the
reservation so a later due run can retry. Ambiguous delivery is never
automatically resent.

### 8. Keep publication deterministic and text-first

Award/result facts come from the award authority. Retail availability, package
and price come from the official retailer source.

Rendering is deterministic. No runtime LLM is needed.

Product photos remain disabled unless exact product identity and explicit reuse
rights are both documented; lack of a photo never blocks a valid text post.

### 9. Do not activate before five broad categories are READY

The production cron must not be installed until at least five independent broad
categories have a fully reviewed award source path and an exact current retailer
verification path.

This launch gate provides roughly fifteen days of runway at the three-day
cadence and prevents the feature from beginning as a short two-product demo.

## Consequences

The steady-state phone cost is tiny:

- non-due days: state read only, zero award HTTP;
- due days: a bounded handful of source and exact-product retailer requests;
- no browser, AI, database, daemon or second schedule.

The design deliberately accepts occasional manual source maintenance when an
award body changes its layout or URL. That cost is preferable to a universal
scraper whose runtime and correctness burden would exceed the value of a
three-day feature.

Source-specific adapters may duplicate a little parsing code. This is
intentional: explicit contracts are easier to audit and recover than a generic
framework spanning unrelated competitions and six retailers.

## Superseded POC mechanisms

The following mechanisms from the unmerged product-award proof of concept are
not part of the accepted runtime architecture:

- separate discovery and publication cron jobs;
- continuous OCU/index discovery;
- per-source first-run baselines;
- persistent seen-item tracking;
- FIFO candidate queue;
- reviewed multi-cheese starter seed;
- daily publication semantics.

The dated research remains valuable for source contracts, exact-SKU findings,
retailer capability and award semantics, but runtime code should be rebuilt from
the smaller model above once the five-category launch gate is satisfied.
