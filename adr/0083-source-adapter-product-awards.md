# ADR 0083: Source-adapter award feed for supermarket own-brand products

- Status: Accepted
- Date: 2026-09-25

## Context

The product goal is broader than one OCU comparison. The group should receive
occasional useful notes about supermarket own-brand products that perform well
in independent tests or competitions: food, cheese, wine, olive oil, jamón and
other categories may come from different award bodies over time.

The first implementation experiment tried to make source interpretation generic
by putting Gemini/OpenRouter in the critical discovery path. That experiment
proved the product idea but made the runtime unnecessarily complex. The model
sometimes confused retailer and private label, sometimes shortened a product
name to the brand alone, and therefore required increasingly elaborate
post-validation and event-identity repair. A later live preview also hit a
Gemini timeout followed by an OpenRouter HTTP 403. None of those failures were
caused by the award source itself.

The same experiment also showed that live supermarket-catalog enrichment is not
a safe core dependency. Mercadona currently exposes two distinct SKUs with the
same visible Salmorejo Hacendado name, while the OCU result page does not
identify enough packaging detail to choose one without guessing.

The feature still needs one shared delivery stream and shared deduplication so
new award sources do not create independent cron jobs, queues or publication
systems.

## Decision

### Shared engine, source-specific adapters

Use one small award engine with source-specific adapters.

Each adapter is responsible for exactly two operations:

- `discover(year) -> tuple[item_id, ...]`: return a bounded set of stable
  source item identifiers;
- `load(item_id, year) -> AwardSourceItem`: fetch and deterministically parse
  that source item into zero or more verified `ProductAwardCandidate` records.

The shared core must not interpret arbitrary source prose. It only:

- iterates registered adapters;
- performs per-source first-run baseline;
- queues verified candidates;
- deduplicates by source-defined event identity;
- renders the approved candidate semantics;
- publishes at most one queued item per local day;
- preserves at-most-once Telegram delivery state.

### Candidate contract

Every adapter returns source-backed fields only:

- `source_kind`;
- stable `event_key` defined by that source adapter;
- `source_url`;
- `retailer`;
- `private_label`;
- `product_name`;
- `result`;
- `award_body`;
- `result_year`;
- optional `score`;
- optional source-published price;
- optional comparison sample size.

The common `event_id` is a hash of `source_kind + event_key`. The shared
engine does not invent a universal product fingerprint and does not use NLP,
fuzzy matching or model-generated wording to establish identity.

An adapter should define `event_key` from the most stable identity exposed by
its own source. Harmless editorial/result changes must not create a duplicate
event when the source clearly represents the same award event.

### Current source

OCU is the first active adapter.

It discovers bounded current food report URLs under
`/alimentacion/.../informe/` and parses only explicit current-year results for
accepted own-brand labels.

The first accepted OCU result types are:

- `Mejor del Análisis`: the best result in that OCU comparative analysis;
- `Compra Maestra`: OCU's value/balance designation, not a claim that the
  product has the highest absolute quality.

The OCU adapter may retain only facts explicitly present in the report, such as
score, number of compared products and a price published by OCU. Missing
optional facts are omitted.

### Future sources

World Cheese Awards, wine competitions, olive-oil awards, jamón awards, Great
Taste or other sources are not implemented through a universal parser.

Each future source gets a small adapter only after a live source investigation
proves:

- an authoritative or official result surface;
- bounded anonymous access suitable for Termux;
- a stable way to enumerate current items;
- a stable event identity;
- exact product/brand/result evidence;
- clear semantics for its award tiers;
- a deterministic fail-closed parser.

Adding a source is then one adapter plus tests and one registry entry. Existing
queue, state, schedule and Telegram delivery stay unchanged.

The state tracks which source names have been initialized independently. Adding
a new adapter therefore silently baselines only that source; it does not reset
existing sources and does not dump historical awards into the queue.

### No AI in the award critical path

Product-award discovery, parsing, identity, rendering and publication do not
require Gemini or OpenRouter.

Do not add:

- universal LLM extraction;
- model voting or same-run model retries;
- AI-derived product identity;
- a generic product-name recovery layer;
- a model-generated event key.

The feature must still work when all AI API keys are absent.

### No live catalogue enrichment in the core

Current supermarket SKU/price/image lookup is not part of the core feature.

A source-published price may be displayed with explicit wording such as
"in the OCU study the stated price is ...". It must not be presented as a live
store price unless a future enrichment contract proves an exact current SKU.

Images, live prices and retailer catalogue data may be reconsidered later as an
optional enrichment layer only when exact identity is unambiguous. Enrichment
failure must never suppress an otherwise valid award post.

The initial production publication is text-only.

### Queue and delivery

Keep one shared queue for every award source.

- Daily discovery: 13:50 Europe/Madrid.
- Daily publication: 14:20 Europe/Madrid.
- Publish at most one queued award per local day.
- First successful observation of each newly added source is a silent baseline.
- Confirmed Telegram send moves an event to permanent published history.
- Before a non-idempotent Telegram send, move the event to uncertain state and
  reserve the daily slot.
- Ambiguous Telegram delivery remains uncertain and is not automatically
  resent.
- Explicit deterministic send failure returns the event to the queue for a
  later day.

Use one small atomic JSON state and the existing Termux cron model. Do not add a
database, daemon, message broker, resident worker or internal scheduler.

## Follow-up: ADR 0084

Later same-day horizontal retailer research broadened the product scope beyond
private labels. ADR 0084 keeps this engine decision intact but separates award
evidence from exact retail evidence so a proven retailer-exclusive or ordinary
currently listed product may also qualify. It also permits one bounded
publication-time exact-SKU price refresh and optional exact-product media after
reuse checks.

This does not reinstate catalogue lookup as award identity, fuzzy product
matching, LLM extraction or mandatory enrichment. Award event identity remains
source-native and independent of changing retailer price, stock or photo.

## Consequences

The feature remains extensible across many product categories without requiring
a universal content-understanding system.

A new award body may require a small custom parser. That duplication is
intentional: source-specific code is cheaper to reason about than one generic
parser whose hidden assumptions have to cover unrelated award sites.

The core becomes insensitive to AI-provider availability and avoids the main
failure modes observed in the first proof of concept.

Some useful data may be omitted when a source changes layout or does not expose
a fact deterministically. This is accepted. A missing award post is preferable
to a wrong product, wrong award tier or guessed current SKU.

## Alternatives considered

### Universal LLM extraction and editorial generation

Rejected for the critical path. Live tests showed unstable entity extraction,
product-name variation, false validation failures and provider availability
failures. The resulting defensive code was becoming more complex than the
feature.

### OCU-only one-off monitor

Rejected as the final architecture. OCU is only the first source; the product
goal explicitly includes cheese, wine, olive oil, jamón and other award
families. A tiny common engine avoids rebuilding queue/delivery logic for every
source.

### Universal scraper/provider framework

Rejected. Sources are too heterogeneous and only a few are expected at first.
Use the smallest adapter contract needed by current demonstrated sources.

### Mandatory live price/photo enrichment

Rejected. Exact SKU identity is not guaranteed by award sources. Publication
must remain useful and correct without retailer catalogue enrichment.

## Implementation checklist for a new source

1. Add a dated research note with the official source, result semantics,
   current-year behavior, request cost and stable identifiers.
2. Prove the source with a read-only live probe before coding scheduled use.
3. Add or verify the retailer/private-label ownership allowlist.
4. Implement one bounded `discover(year)`.
5. Implement one deterministic `load(item_id, year)`.
6. Define a source-native stable `event_key`; do not derive it from generated
   prose.
7. Return only source-backed candidate fields and fail closed on ambiguity.
8. Add source-specific renderer semantics only where the generic wording would
   misstate the award.
9. Add unit tests for positive, negative, stale-year, duplicate and layout-edge
   cases.
10. Run a live read-only adapter probe.
11. Register the adapter only after those checks pass.
12. Verify that a first production discovery baselines the new source without
    publishing its historical catalogue.
