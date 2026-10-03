# Product Awards post-production full review — 2026-10-03

## Scope

Full second-pass review after ADR 0095 was production-validated.

This review deliberately reopens assumptions across:

- source admission;
- reviewed registry;
- retailer identity/current-price proof;
- category/source/rank selection;
- retailer-diversity preference;
- state/cooldown/deduplication lifecycle;
- media degradation and Telegram at-most-once safety;
- editorial rendering;
- long-run operation on Termux.

No runtime code is changed by this review.

## Overall assessment

The core runtime architecture is appropriately small and is **not
overengineered**:

- one daily one-shot;
- zero source HTTP during cooldown;
- finite category scan only when due;
- one in-memory same-retailer fallback;
- no discovery queue, browser, JS, AI, database or resident process;
- source-specific bounded adapters;
- image failure cannot suppress a verified text publication;
- ambiguous Telegram delivery still blocks automatic resend.

The retailer-preference logic is also correct for the accepted product rule:
publication is primary and retailer diversity is only a preference. A
same-retailer candidate is retained and published when no different-retailer
candidate survives verification.

However, the solution is **not fully complete**. The review found material
editorial/correctness gaps plus several medium-term robustness risks.

## Finding 1 — HIGH: current renderer lost mandatory editorial facts

Earlier accepted Product Awards requirements include:

- country of producer/production in every publication;
- exact package/volume/weight for the current retail product;
- all exact current package/price variants when one awarded product has more
  than one qualifying current package;
- product + supermarket + award in the headline;
- the open editorial text should explain why the winner stood out, rather than
  replacing that explanation with generic methodology.

The current `ReviewedCandidate` / `RetailOffer` model has no production
country/producer fields and no explicit package field.

The current generic OCU renderer uses only:

- product name;
- source category;
- award/result;
- sample size;
- current price.

Consequences visible in the live preview:

- Realfooding does not say `1 l` or country/producer;
- Oleoestepa does not say `1 l` or country/producer;
- AROM'ARTE does not say `20 unidades` in the article body/headline;
- Anís Chinchón does not say `1 l` or Spain in the article copy;
- OCU headlines can contain a numeric score but omit the retailer;
- unique source facts explaining why the winner stood out were replaced by one
  generic expandable methodology paragraph.

This is a regression of the editorial contract, not a source/runtime-safety
failure.

### Recommended repair boundary

Do not add runtime AI.

Add reviewed deterministic editorial facts to each candidate, or small
source-specific rendering fields, sufficient to express:

- exact package;
- producer and country;
- retailer in headline;
- source-proven winner-specific reason/highlight.

When multiple exact current packages of the same awarded identity exist, the
retailer adapter/model must either return all qualifying variants and prices or
explicitly prove that the award is tied to only one exact package.

## Finding 2 — HIGH: Carrefour exact page is not local-availability proof

Earlier Carrefour research explicitly noted that Carrefour resolves product
availability through postcode/store context and recommended restricting retail
evidence to the supermarket surface plus a configured postcode/store context.

The restored `_html_retail_offer()` performs a plain bounded GET of the exact
Carrefour URL with browser-navigation headers, but no postcode, store, cookie or
other locality context.

Current official Carrefour product pages themselves ask for a postcode
`para ver la disponibilidad de productos en tu zona` before shopping.

Therefore the current proof establishes:

- the exact Carrefour supermarket catalogue product exists;
- the generic page exposes a price and an `Añadir` control.

It does **not** prove that this product is available in the Guardamar delivery /
store context, nor that the displayed default web price is the locally
applicable price.

This conflicts with the earlier retailer-evidence decision and weakens the
literal public wording `Сейчас этот товар в Carrefour стоит ...`.

### Recommended repair boundary

Before publication, either:

1. establish one cheap deterministic Guardamar-area Carrefour postcode/store
   contract; or
2. weaken the public claim to what the generic official page actually proves
   and stop treating it as local availability.

Do not add a browser/session framework merely to solve this. If a bounded
postcode/store contract cannot be proved, fail closed or use more precise
wording.

DIA should be checked for the same locality issue, but this review does not
claim a DIA defect without equivalent source evidence.

## Finding 3 — MEDIUM: Carrefour/DIA identity markers are page-global

`_html_retail_offer()` validates `retailer_markers` against the whole visible
page, while only the price search is scoped around the exact title.

On an exact product URL this is reasonably strong, but recommendations,
navigation content or related products could theoretically supply one of the
markers outside the actual product card.

The implementation therefore does not fully satisfy the strongest possible
interpretation of “all exact identity qualifiers belong to the same product
object/card”.

### Recommended repair boundary

Keep the exact URL and title requirement, but scope category-critical markers to
the same product-detail region when that can be done cheaply and
deterministically. Avoid building a generic DOM framework.

## Finding 4 — MEDIUM: HTML price parser can choose the wrong price on promotions

`_price_after_title()` returns the **first** positive `X,XX €` value between
the exact title and the nearest `Añadir`.

That is correct for the four currently validated cards, but the algorithm has
no semantics for cards that expose two distinct prices, for example:

- old regular price + current promotional price;
- current price + member/Club price;
- package price + another non-unit monetary value.

A future promotion could therefore produce a syntactically valid but wrong
“current price”.

### Recommended repair boundary

Do not guess “first” or “last” once multiple distinct prices are present.

Either parse a reviewed source-specific current/old-price label/markup or fail
closed on an ambiguous multi-price card. Add fixture coverage for promotional
price ordering before enabling such a case.

## Finding 5 — MEDIUM: publication history has a hard 128-entry lifetime ceiling

State is deliberately bounded with `MAX_HISTORY = 128`.

`confirm()` raises `STATE` when either published-events or
published-selections reaches 128 entries. There is no rollover/compaction
policy.

At one publication every three days, the theoretical ceiling is roughly one
year of confirmations.

More importantly, the failure happens **after Telegram may already have
confirmed the new message**. The existing uncertain reservation prevents an
automatic duplicate, so this is safe from double-send, but the feature can then
remain blocked by an uncertain event until operator repair.

### Recommended repair boundary

Design a bounded compaction policy before history approaches the cap. Do not
solve this by silently discarding arbitrary recent dedup keys.

A simple policy should preserve:

- all event/selection identities still present in the current reviewed
  registry;
- the last confirmed event needed for retailer preference;
- enough historical identity to prevent deliberate reintroduction of recently
  published editions.

This is not urgent for tomorrow's publication but is a real lifecycle bug.

## Finding 6 — MEDIUM: current runway is short and exhaustion is operator-silent

Production state already contains Mahou as published. NALTROS is currently
unavailable with `RETAIL-PAGE-ERROR`.

That leaves five currently publishable unpublished categories:

- Realfooding;
- Oleoestepa;
- AROM'ARTE;
- Anís Chinchón;
- Ambar.

At the accepted three-day cadence this is about fifteen days of runway if
source availability remains stable.

Registry exhaustion is intentionally cheap and safe: the bot makes zero source
requests and logs `registry is exhausted`. But there is no operator-facing
notification.

This is acceptable architecture only if candidate research is treated as an
ongoing editorial maintenance task. Otherwise “silence after exhaustion” can
look like another bot failure, conflicting with the practical goal of keeping
the feature publishing.

### Recommended repair boundary

Do **not** restore autonomous discovery, queueing or AI.

Maintain a small manual/reviewed runway target (for example several unpublished
READY categories ahead) and check it during normal repository maintenance.
Only add an operator status command/notice if manual maintenance proves easy to
miss.

## Finding 7 — MEDIUM/LOW: preview is catalogue-oriented, not “what posts next”

`product-awards-preview` verifies each category independently and prints all
currently valid category publications. It does not apply production state,
published-history deduplication, cursor or retailer preference.

That is useful as a source-contract diagnostic, but the command name can mislead
an operator: it showed already-published Mahou and does not itself answer
“which message will the next scheduled run select?”

### Recommended repair boundary

Keep the existing all-category preview for diagnostics, but make its purpose
explicit in output or add one small read-only state-aware “next” view. Do not
change the selector merely for operator UX.

## Finding 8 — LOW: ADR 0083 retailer-set wording is stale

ADR 0083 still states that the supported retailer set is “exactly” six chains
(Mercadona, Carrefour, ALDI, Lidl, DIA, Consum).

Later accepted research expanded the primary set to seven by adding Valencian /
Murcian Masymas, and production already contains/published Mahou through
Masymas.

The runtime behavior is consistent with the later decision; the old ADR wording
is not.

### Recommended repair boundary

Add an explicit amendment/superseding note to ADR 0083 pointing to the later
seven-chain decision. No runtime change is needed.

## Finding 9 — LOW: known Russian declension defect

The production preview currently renders:

`сравнила 23 продуктов`

instead of:

`сравнила 23 продукта`.

This is presentation-only and was already recorded during production
validation.

A small deterministic Russian-number helper would be cleaner than a one-off
literal patch if sample sizes will vary, but do not build a general localization
framework.

## What is already sound

No change is recommended to these parts:

- three-local-calendar-day cooldown;
- daily retry after a due run fails to publish;
- one-publication-per-local-day force guard;
- source-priority/rank semantics;
- best-effort previous-retailer preference with same-retailer fallback;
- deriving previous retailer from existing published-event history rather than
  adding retailer state;
- Consum media precedence;
- optional media / no-image delivery;
- ALDI `hasError=true` classification;
- uncertain-delivery reservation and at-most-once fallback behavior;
- exclusive local run lock;
- no browser/AI/queue/database architecture.

## Overengineering assessment

The current runtime itself is lean.

The main risk now is the opposite of overengineering: several editorial and
retail-evidence requirements were simplified away while repairing reliability.

The correct next change should therefore be **contract restoration**, not a new
framework.

Recommended priority:

1. restore mandatory editorial facts/packaging/country/winner-specific reasons;
2. resolve Carrefour locality semantics;
3. harden ambiguous multi-price HTML parsing;
4. tighten same-card marker scope if the source layout permits it cheaply;
5. plan bounded state-history compaction before long-term growth;
6. keep replenishing the reviewed candidate runway;
7. clarify preview semantics and stale ADR wording;
8. fix the Russian declension.

Until items 1–2 are resolved, the runtime is technically safe but the
user-facing Product Awards contract is not fully satisfied.
