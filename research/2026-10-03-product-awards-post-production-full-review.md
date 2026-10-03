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


## Third-pass adversarial review — refined repair plan

A second adversarial pass over the proposed remediation changes several
priorities.

### Confirmed: the core architecture still does not need redesign

The following remain correct and should not be touched:

- one daily short-lived Product Awards invocation;
- three-local-calendar-day cooldown;
- state-first zero-HTTP cooldown exit;
- one finite category scan;
- source-native rank semantics;
- one same-retailer in-memory fallback;
- publication-first retailer diversity;
- existing state schema for retailer preference;
- media-optional delivery;
- ambiguous-send protection;
- no browser, AI, queue, database, background worker or generic retailer
  framework.

The primary risk is now accidental scope growth while repairing presentation
and evidence wording.

### Revision A — editorial contract is the only immediate blocking repair

The editorial regression remains real.

However the correct repair is **not** to restore the old rich POC schema or add
a generic multi-variant product model.

For the current reviewed registry, add only the deterministic facts needed by
the accepted article contract:

- exact package/format for the reviewed retail identity;
- verified production country;
- verified producer/manufacturer when available and useful;
- retailer in the headline;
- one source-proven product-specific highlight/reason.

Keep score/detail in the body rather than making a numeric score the headline.

If an award-to-retail join cannot prove which package carries the award, keep
that candidate unready rather than implementing arbitrary package discovery.

The earlier requirement to show all prices/packages should be interpreted
narrowly: show all **already reviewed exact qualifying package variants** for
the same award identity. The current registry has one exact reviewed retail
format per candidate, so a list-of-variants runtime abstraction is not needed
now.

### Revision B — Carrefour locality should not trigger browser/session work

The generic Carrefour page does not prove Guardamar-specific stock. That fact
remains true.

But current Product Awards requirements need a fresh official retailer price
for an exact product; they do not require proof that a particular Guardamar
physical shelf contains it at that moment.

Therefore the least-complex correct repair is semantic:

- keep the exact first-party Carrefour supermarket product page as current
  online retail evidence;
- phrase the claim as e.g. `На сайте Carrefour сейчас указана цена ...`;
- do not claim Guardamar-local stock or a local-store-specific price;
- research a postcode/store contract only if future product requirements
  explicitly require local availability.

Do not add cookies, session bootstrap, a browser or a postcode API solely to
preserve the broader wording `в Carrefour стоит`.

This demotes the previous locality finding from an immediate blocker to a
wording/evidence-precision fix.

### Revision C — page-global extra markers are not worth a parser framework

Exact Carrefour/DIA URL + exact reviewed product title + price found in the
title-to-`Añadir` region already provide the main identity boundary.

Page-global manufacturer/qualifier markers are a secondary defense.

Tightening every marker to a DOM-like product region would add complexity and
could reject legitimate details rendered outside the buy card.

Do not build a generic DOM/product-region parser now.

If a future live incident shows a false positive from recommendations or
related products, add one source-specific boundary for that retailer.

### Revision D — promotion-price ambiguity is real, but needs evidence before code

The current first-positive-price algorithm can theoretically misread a future
promotion.

A naive `multiple prices => fail` fix may itself be wrong because a card can
legitimately show:

- package price;
- reference price per litre/kg;
- regular price;
- club/promotional price.

Before changing runtime, perform one read-only raw-HTML probe on current
Carrefour/DIA cards, ideally including a promotional item, and document the
actual markup/labels.

Then implement the smallest source-specific rule.

Do not guess `first`, `last` or `minimum` as a universal current-price
algorithm.

### Revision E — MAX_HISTORY=128 is a real boundary, but not urgent

The previous review overstated the time-to-failure by assuming a publication
every three days forever.

The reviewed registry is manually replenished and currently small, so actual
history growth is likely much slower.

The dangerous property is not the number 128 itself; it is that capacity is
checked inside `confirm()`, after Telegram may already have returned success.

The eventual repair should therefore prioritize **pre-send capacity
validation**.

A larger bounded cap (for example 512) can be considered as a simple
operational margin, but compaction/rollover logic should not be introduced
without an actual retention policy.

Do not implement a complex historical-pruning algorithm now.

### Revision F — runway is an editorial maintenance issue, not a scheduler bug

With Mahou already published and NALTROS currently unavailable, the present
registry has about five immediately publishable unpublished categories.

At the three-day cadence that is about fifteen days of runway.

Do not respond with autonomous discovery, retailer scans, queueing or an
operator alert subsystem.

Continue reviewed source-first candidate research and keep a practical manual
runway buffer.

Only automate runway warnings if maintaining that buffer proves unreliable in
practice.

### Revision G — preview UX is useful but optional

The existing `product-awards-preview` is correctly a catalogue/source-health
preview, not a selector simulation.

Do not change its selection semantics.

A future small `product-awards-next-preview` command would be useful because
the operator frequently asks which post is next, but this is convenience, not
correctness.

If added, it should call the real state-aware selector read-only and clearly
identify itself as the next scheduled candidate.

### Revision H — ADR 0083 retailer wording is stale, runtime scope is not

The old ADR 0083 text says the retailer set is exactly six chains.

Later accepted Product Awards work explicitly productionized Masymas exact
retail identities (ADR 0084 / Decision Log), so Mahou/Masymas is not an
accidental runtime scope leak.

The repair is documentation only: add an amendment pointing to the later
seven-retailer scope.

### Revision I — NALTROS tie semantics are valid

The OCU cava source has three products tied at 94/100.

Reviewed research explicitly permits tied candidates to retain tie semantics,
prefer one with a verified exact retail match, and preserve source order when
needed.

NALTROS is therefore valid as a tied top-score candidate provided public wording
continues to say `один из лидеров` rather than unique #1.

No rank-logic change is needed.

### Revised implementation order

**Before the next Product Awards publication:**

1. restore the lean deterministic editorial contract:
   package, verified country/producer facts where supported, retailer in the
   headline and a source-proven winner-specific highlight;
2. change Carrefour wording from a broad/local-sounding price claim to an
   explicit official-site price claim;
3. fix Russian sample-count declension.

**Next hardening pass, after one read-only source probe:**

4. inspect real Carrefour/DIA promotional price markup and then harden price
   extraction only if a deterministic current-price rule is proved.

**Deferred maintenance:**

5. add pre-send Product Awards history-capacity validation before history gets
   large;
6. optionally raise the bounded history cap rather than designing compaction
   now;
7. replenish candidate runway;
8. optionally add a state-aware next-preview command;
9. amend ADR 0083 retailer-set wording.

### Final third-pass assessment

The previous full review correctly identified real weak spots, but its first
repair plan would have risked overengineering Carrefour locality, HTML parsing
and state retention.

The smallest coherent next change is an **editorial-contract restoration plus
precise retailer-price wording**, not a new retailer/session architecture.

No reason was found to redesign the selector, cooldown, retailer preference,
delivery state machine or Product Awards scheduling.


## Fourth-pass review — final corrections to the repair scope

A fourth adversarial pass found three additional issues and revalidated several
previously questioned source decisions.

### New finding A — HIGH: current retailer-image use conflicts with the accepted reuse-rights rule

ADR 0083 says product photos remain disabled unless exact product identity and
explicit reuse rights are documented.

ADR 0093 repeats the same boundary: if retailer media reuse is unclear, the
product remains eligible but publication should use the no-image article.

Current runtime can still publish retailer product images for ALDI, Consum and
Masymas when their adapters return an image URL.

Current legal-source evidence is not sufficient to permit that behavior:

- Consum's official legal notice expressly prohibits reproduction,
  distribution and public communication of site content except personal/private
  use;
- Masymas / Juan Fornés' official legal notice expressly excludes reproduction,
  distribution, transformation and public communication without prior
  permission;
- no reviewed Product Awards record establishes an explicit ALDI reuse grant for
  the exact product image.

Therefore the current active rich-media path does not satisfy the project's own
accepted media policy.

This is both a compliance/correctness gap and a complexity smell: the
remote-image -> local-download -> multipart-upload recovery machinery currently
serves media that the production registry should not publish unless reuse rights
are independently documented.

#### Recommended repair boundary

For the current registry, default every candidate to text-only Product Awards.

Do not infer permission from first-party hosting or technical accessibility.

The simplest coherent runtime is:

- exact award;
- exact current retailer product;
- current price;
- deterministic text article;
- no retailer image unless an explicit candidate/media contract records a
  reusable image right.

If no current candidate has such a right, remove or disable the active
Product-Awards media delivery branch rather than maintaining it as production
behavior. A future explicitly licensed source can reintroduce the small
capability under a new reviewed contract.

This finding supersedes the prior assumption that the existing Consum/Masymas
image contracts are automatically acceptable because they are first-party.

### New finding B — MEDIUM: positional category_cursor is coupled to registry shape

State stores `category_cursor` as an integer index into `CATEGORIES`.

That is safe for the current seven-category registry and current production
cursor 0, but Product Awards deliberately uses a manually maintained registry
whose categories can be added, removed or reordered.

Consequences of a future structural registry edit:

- reordering categories silently changes what the same stored cursor means;
- shrinking the registry can make an otherwise valid state fail validation when
  `category_cursor >= len(CATEGORIES)`;
- a deployment therefore depends on preserving positional layout or performing a
  manual/migration-aware state check.

The 3 October rebuild avoided this only because it deliberately kept seven
categories and production cursor 0.

#### Recommended repair boundary

This is not urgent for the next publication.

Before the next registry change that alters category count/order, choose one of
two small approaches:

1. migrate the cursor to a stable category key / last-category key; or
2. explicitly migrate/normalize the existing cursor as part of that registry
   change and encode the mapping in tests/deployment validation.

Do not add a generic migration framework merely for this.

A stable category key is cleaner long-term if registry restructuring becomes
normal.

### New finding C — LOW/MEDIUM: production registry lacks static uniqueness invariants

Current production registry was machine-checked during this review and contains
no duplicate:

- category keys;
- event IDs;
- selection keys.

However, the test suite does not currently enforce those invariants.

Because `published_events` and `published_selections` drive deduplication, a
future hand-edited duplicate could make one candidate silently suppress another.

#### Recommended repair boundary

Add one small registry-invariant unit test asserting uniqueness of:

- `ReviewedCategory.key`;
- every production `event_id`;
- every production `selection_key`;
- source priorities within a category where appropriate;
- candidate ranks within one source where appropriate.

No runtime validation or framework is needed.

### Revalidation: NALTROS tie semantics are correct

The reviewed OCU cava comparison has three products tied at 94/100.

The source-policy research explicitly permits tied top candidates to retain the
tie semantics and use a candidate with a verified exact retail match without
inventing a unique #1.

NALTROS wording remains `one of the leaders`, not unique winner.

No change is needed.

### Revalidation: Oleoestepa READY status is evidence-backed

The earlier strict research initially marked AOVE pending because the reviewed
surface did not yet prove exact OCU winner identity.

A later 27 September source re-check added new evidence: OCU's official
23-product AOVE material explicitly states that the ranking is led by AOVE
Oleoestepa DOP Estepa, and current exact Carrefour identity was then proven.

Therefore ADR 0095 did not improperly promote an unresolved candidate; it used
newer reviewed evidence.

No source-policy change is needed.

### Revalidation: World Beer Awards country-winner semantics are current

Current official World Beer Awards 2026 pages still identify:

- Ambar Especial as Spain Country Winner in International Lager;
- Mahou Sin Filtrar as Spain Country Winner in Classic Pilsener.

Their public wording must remain country/category winner semantics rather than
World's Best.

No rank/source change is needed.

### Revised final implementation order after four reviews

**Immediate, before the next normal Product Awards publication:**

1. restore the lean deterministic editorial contract:
   - package/format;
   - verified production country;
   - verified producer/manufacturer where supported;
   - retailer in the headline;
   - source-proven winner-specific highlight/reason;
   - keep score out of the headline;
2. make Carrefour wording explicitly about the current official-site price,
   not Guardamar-local stock;
3. fix Russian sample-count declension;
4. disable retailer images for every current candidate unless explicit reuse
   rights are documented.

**Small hardening bundled with the same or next tiny change:**

5. add static production-registry uniqueness tests.

**Evidence-first follow-up:**

6. probe real Carrefour/DIA promotional-price markup before changing price
   extraction.

**Deferred lifecycle maintenance:**

7. add pre-send history-capacity validation before state approaches the cap;
8. address positional cursor coupling before a future registry count/order
   change;
9. replenish candidate runway;
10. optionally add a state-aware next-preview command;
11. amend stale ADR 0083 retailer-count wording.

### Fourth-pass overall conclusion

The selector, cooldown, retailer diversity, source/rank order and Telegram
at-most-once state machine still do not need redesign.

The strongest newly discovered simplification is that Product Awards should be
text-only under the current evidence. This removes a policy contradiction and
also makes the media-recovery machinery unnecessary as active production
behavior.

The next implementation should remain a compact contract-restoration change,
not another architecture rewrite.
