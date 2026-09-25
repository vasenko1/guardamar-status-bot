# Supermarket product awards: source and implementation research

## Question

How should the Guardamar Telegram bot build one long-lived editorial stream of
award-winning supermarket own-brand products while staying cheap, deterministic
and easy to extend across unrelated award bodies?

The intended product is not an OCU-only feature. OCU is the first source, but
the same stream should later be able to include cheese, wine, olive oil, jamón
and other products from different competitions without creating a separate
publication subsystem for every category.

## Sources and systems checked

### OCU

- Owner: Organización de Consumidores y Usuarios.
- Discovery surface used by the prototype: `https://www.ocu.org/ocu-salud`.
- Reviewed report:
  `https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos`.
- Access/probes: September 2026.
- Why useful: OCU publishes explicit comparative-test result labels and
  product/brand names in human-readable HTML.

### World Cheese Awards / Guild of Fine Food

- Owner: Guild of Fine Food.
- Directory surface:
  `https://gff.co.uk/directory/?type=product`.
- Access/probes: September 2026.
- Why useful: official result directory with explicit medal terminology.
- Current limitation observed during the POC: the 2026 year/results were not
  yet present in the directory on 25 September 2026, so there was no real 2026
  private-label result set to validate against.

### Retailer catalogues tested during the POC

- Mercadona public catalogue/Algolia path.
- ALDI España public search.
- Lidl España public search.

These were evaluated only for optional price/image enrichment, not as award
authorities.

### Runtime AI experiment

The first POC also tested Gemini structured extraction with OpenRouter as the
existing secondary provider. This was an implementation experiment, not an
award source.

## Product scope

The user-facing concept is one occasional stream:

- one day an OCU-tested Hacendado product;
- another day a cheese with a World Cheese Awards medal;
- later a wine, olive oil, jamón or another supermarket own-brand product from
  a credible independent competition.

The stream should feel like useful editorial discovery, not advertising and not
a technical bot card.

The system should smooth bursts rather than publish several awards at once.
The accepted schedule is one discovery run followed by at most one queued
publication per day.

## Retailer/private-label ownership allowlist

The POC established a conservative own-brand allowlist:

- Mercadona: Hacendado.
- Consum: Consum, Consum Eco, Consum Kids, Kyrey, Vitality.
- ALDI: La Tabla, Milsani, Cucina, Moser Roth, GutBio.
- Lidl: Roncero, Deluxe, Milbona, Chef Select, Crownfield, Freshona, Gelatelli,
  Vemondo, J.D. Gross, Favorina, La Cestera, Realvalle, Ocean Sea.
- Carrefour: Carrefour, Carrefour Classic, Carrefour Extra, Carrefour Original,
  Carrefour Sensation, Carrefour El Mercado.
- Valencian Masymas / Juan Fornés: Alteza, Deleitum.

Do not infer own-brand ownership from a retailer name, manufacturer name or
seller relationship. Extend the allowlist only after a retailer-owned source
or other strong evidence establishes the relationship.

When labels overlap, prefer the most specific exact label. For example,
`Carrefour Extra` is not reduced to the parent `Carrefour`.

## OCU findings

### Result semantics

Keep OCU wording semantically exact:

- `Mejor del Análisis` means the best result in the specific OCU comparative
  analysis. It is not a generic medal or a universal category championship.
- `Compra Maestra` is a value/balance distinction. Do not describe it as the
  highest-quality product merely because it is selected by OCU.

These two outcomes may coexist in one comparison and may belong to different
products.

### Salmorejo case used for live validation

The 2026 OCU salmorejo report provided a strong real test case:

- private label: Hacendado;
- retailer: Mercadona;
- product: salmorejo fresco de Hacendado;
- result: Mejor del Análisis;
- score: 70/100;
- comparison size: 30 salmorejos;
- the source also states that it was the best-rated product in the professional
  tasting.

The report was repeatedly fetched and parsed during development. The important
lesson is that these core facts are already explicit enough for deterministic
source parsing; a language model is not necessary to decide what the award is
or which private label owns the result.

A price published inside an OCU report is optional source metadata. If parsed,
render it explicitly as a price stated in that study. It is not evidence of the
current shelf price.

### Discovery choice

For production discovery, use OCU food report URLs under
`/alimentacion/.../informe/`.

Do not depend on OCU news articles as a second discovery stream for the same
test. A report is a cleaner stable unit and avoids duplicate news/report
representations of one comparison.

A current-year report is accepted only when the adapter can establish the
report year and parse an explicit accepted result next to an allowed private
label. Ambiguous layout changes fail closed and leave the item eligible for a
future retry.

## World Cheese Awards findings

WCA is still a good future source, but it should not be generalized before
there is current real data to validate.

The official directory exposed the concepts needed by a future adapter:

- current/result year;
- product identity;
- explicit award level such as Super Gold, Gold, Silver or Bronze.

Important semantic rule: a medal tier is not automatically "first place in the
category". Never invent a category win unless the official result explicitly
says so.

Implementation should wait until 2026 results exist in the official directory.
At that point, capture the actual HTML/query contract and define the adapter's
stable event key from the real result representation.

## Optional catalogue-enrichment experiment

The POC tested live retailer catalogue lookup because a current price and exact
product photo would make posts more attractive.

The experiment showed why this must not be a core dependency.

### Mercadona

A live Salmorejo search returned at least two different current SKUs with the
same visible product name:

- SKU 39901: Salmorejo fresco Hacendado;
- SKU 39966: Salmorejo fresco Hacendado.

The OCU article did not expose enough package-size identity to choose between
those SKUs without guessing. Therefore a seemingly straightforward
"exact-name" match can still attach the wrong current price or image.

### ALDI and Lidl

Public search endpoints were technically usable during the POC, but that does
not solve the general identity problem. Catalogue availability and naming are
retailer-specific.

### Other retailers

No equally reliable low-cost exact-SKU price path was established for Consum,
Carrefour or Valencian Masymas during the POC.

### Conclusion

Do not make live retailer catalogue lookup part of award discovery or
publication eligibility.

If enrichment is revisited later:

- it must be optional;
- it must prove exact SKU identity;
- ambiguity means no enrichment;
- no result may be blocked because price/photo is missing;
- source-published award facts remain authoritative.

## What the LLM POC taught us

The first implementation intentionally explored whether one universal model
call could turn arbitrary award pages into a common candidate contract.

It worked often enough to prove the product idea, but repeated live runs exposed
several distinct failure classes.

### Entity-role instability

For the same OCU Salmorejo source and same code, Gemini returned:

- `private_label = Hacendado` in some runs;
- `private_label = Mercadona` in another run.

The source evidence itself still correctly contained
`salmorejo fresco de Hacendado (Mercadona)`.

This forced the code to stop trusting the model for brand ownership.

### Product-name instability

Later repeated runs returned both:

- `salmorejo fresco de Hacendado`;
- only `Hacendado`.

When event identity depended on the model's product wording, one real award
became two event IDs. A deterministic `product_key` layer was added to repair
this, but that layer existed only because the model had been put in charge of
source interpretation.

### Editorial validation mismatch

A Russian editorial note could correctly transliterate or translate a Spanish
product name while a literal validator expected the Spanish token. Correct
prose was therefore rejected even though the verified facts were present.

### Provider availability

A final live editorial preview hit:

1. Gemini read timeout;
2. OpenRouter fallback HTTP 403;
3. complete failure of the award path before publication preview.

The award source itself was healthy.

### Architecture conclusion

The failure pattern was not one isolated bug. Each repair created another
generic layer:

- model field validation;
- deterministic private-label repair;
- product-key recovery;
- source retry semantics for rejected model output;
- editorial-result validation;
- secondary-provider behavior.

That is unnecessary for sources whose award facts are explicitly published.

The experiment should be retained as evidence not to reintroduce universal LLM
extraction into this feature.

## Accepted architecture

Use one shared engine plus small source adapters.

A source adapter owns source-specific interpretation. The shared engine owns
only common operational behavior.

### Adapter contract

Each adapter provides:

- `name`;
- `discover(year)`: bounded current item identifiers;
- `load(item_id, year)`: one deterministic parse returning an
  `AwardSourceItem`.

The item contains zero or more verified `ProductAwardCandidate` records.

### Candidate contract

Current common fields:

- source kind;
- source-defined event key;
- source URL;
- retailer;
- private label;
- product name;
- result;
- award body;
- result year;
- optional score;
- optional source-published price;
- optional sample size.

The source adapter defines the stable `event_key`. The common engine hashes
`source_kind + event_key` into the persistent event ID.

This is intentionally different from a universal normalized product identity.
The source that knows the award representation is the right place to define
what constitutes one event.

### Per-source baseline

State records initialized source names independently.

When a new adapter is deployed:

1. its first successful discovery marks the existing item IDs as seen;
2. historical results are not queued;
3. already active sources keep their state unchanged;
4. later new items from that adapter enter the shared queue normally.

This is important for incremental expansion: adding wine awards in the future
must not reset OCU or publish an archive of old wine medals.

### Shared queue and delivery

The queue is global across sources.

- Discover at 13:50 Europe/Madrid.
- Publish at 14:20.
- FIFO is sufficient for the MVP.
- At most one award post per local day.
- A burst from several sources is naturally spread across later days.
- Published and uncertain event histories permanently block duplicate enqueue.
- Ambiguous Telegram send stays uncertain and is never automatically resent.
- Explicit deterministic send failure may safely requeue for a future day.

### Rendering

Rendering is deterministic and source-semantic.

OCU needs explicit wording for `Mejor del Análisis` and `Compra Maestra`.
A future medal source may use a generic medal sentence only when that wording
does not overstate the award.

Do not add a language model merely to make the prose less repetitive. The
volume of awards is low, and small reviewed templates are cheaper and safer.

### Runtime footprint

The desired no-change run is:

- one bounded discovery request per active source family;
- no browser;
- no OCR;
- no PDF;
- no AI;
- no retailer catalogue query;
- one small JSON state;
- no resident award process.

## Implementation recipe for the next award source

Before coding:

1. Identify the official/authoritative result source.
2. Record the exact result semantics. A `Gold`, `95 points`, `Best Buy`
   and category winner are not interchangeable.
3. Prove a bounded anonymous request from the Termux environment.
4. Find a current-item list or another cheap change-detection surface.
5. Find a stable source-native item/event identity.
6. Confirm how the exact product brand is represented.
7. Confirm private-label ownership independently.

Then implement:

1. `discover(year)` returning bounded item IDs.
2. `load(item_id, year)` with strict host/content/size bounds.
3. A fail-closed parser for only the facts the source explicitly supplies.
4. A source-native `event_key`.
5. Candidate mapping into the common contract.
6. Tests for:
   - current positive result;
   - third-party brand rejection;
   - old-year rejection;
   - ambiguous product rejection;
   - duplicate item/event behavior;
   - known award-tier semantics;
   - parser breakage leaves the item retryable.
7. A read-only live probe.
8. Registration in `SOURCE_ADAPTERS` only after the live probe passes.
9. A first production discovery proving silent baseline for the new source.

Do not create a new queue, cron, publisher, state file or notification
framework for the new source.

## Candidate future source families

These remain research candidates, not production commitments:

- World Cheese Awards / Guild of Fine Food;
- wine competitions with official searchable result databases;
- olive-oil competitions;
- jamón/cured-meat competitions;
- Great Taste and similar food-award directories.

Prioritize sources that have official structured or stable HTML results and
clear product identity. A prestigious award with an expensive or ambiguous
source is lower priority than a slightly less broad award with a clean,
verifiable public result surface.

## Status and next validation

Architecture: accepted.

Implementation: PR #195.

Production deployment: not yet approved at the time of this note.

Before merge/deploy, the deterministic branch still needs the normal final
read-only live preview and full regression review. That preview must work with
Gemini, OpenRouter and Telegram credentials unset.
