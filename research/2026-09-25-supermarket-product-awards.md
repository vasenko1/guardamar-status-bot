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

---

## Horizontal retailer and rich-editorial expansion — 25 September 2026

### Scope after the second research pass

The first proof of concept intentionally constrained the feed to supermarket own brands. The broader useful scope is now:

- private-label products;
- retailer-exclusive products whose exact commercial identity can be proven;
- ordinary branded products that have won a credible award and whose exact SKU is currently listed by a supported Spanish supermarket.

Public wording must preserve those distinctions. A listed or retailer-exclusive product must never be described as an own brand unless ownership is independently proven.

The user-provided Salmorejo article is deliberately not stored as a project template or copied into this research. It is only a quality bar: a publication should contain enough verified material to explain what was tested, how the result was obtained, why the product stood out, and — when exact current retail identity is proven — the current price and an exact product photo.

### Target retailer set

The primary set should be seven Spanish supermarket chains:

1. Mercadona;
2. Lidl España;
3. ALDI España;
4. Consum;
5. Carrefour España supermarket;
6. Masymas / Juan Fornés Fornés in Comunidad Valenciana and Murcia;
7. DIA España.

DIA is a justified addition rather than generic chain expansion.

DIA has a live official page for its 2026 Sabor del Año products with exact private-label products and current prices:
https://www.dia.es/l/productos-premiados-dia

Eroski and SPAR remain possible later additions. They are not needed for the first expansion.

### Retail catalogue capability

#### Mercadona

Public product URLs use a numeric product identity under:
https://tienda.mercadona.es/product/<id>/<slug>

The earlier POC proved that public catalogue/search data can expose exact Mercadona SKU IDs, prices and product images.

The critical identity finding remains: SKU 39901 and SKU 39966 both exposed the visible name Salmorejo fresco Hacendado. Therefore visible-name equality is never enough. An exact Mercadona product ID or another exact variant discriminator is required before current price or photo can be attached.

Decision: technically usable, but the strictest matching rules are required.

A 26 September 2026 browser-free probe established a concrete Guardamar
contract:

- postal code `03140` resolved to warehouse `alc1`;
- exact product endpoint:
  `https://tienda.mercadona.es/api/products/<id>/?lang=es&wh=alc1`;
- reviewed SKU `50952` returned:
  `Queso añejo tostado mezcla Hacendado`,
  EAN `8480000509529`, `published=true`,
  supplier `Queserías Entrepinares S.A.U.`,
  unit price 6.19 EUR, approximate size 0.37 kg and reference price
  16.74 EUR/kg;
- the exact retail ingredient field identifies pasteurized cow milk 50%,
  sheep milk 20% and goat milk 15%.

The warehouse was returned in the postal endpoint response headers rather than
its JSON body. To avoid an extra request and shared-transport changes on every
publication, the MVP uses reviewed Guardamar warehouse `alc1` and fails closed
if the exact product response changes. No catalogue search is performed.

If the award source does not distinguish an exact Mercadona product strongly
enough, do not enrich or publish it rather than guess.

#### Lidl España

Lidl has the strongest retailer-side award discovery surface found:
https://www.lidl.es/c/premiados/a10092875

On 25 September 2026 it exposed awarded groups across fresh salmon, beef, cheeses, fish, wine and other products, with current availability and often price/package data.

Observed examples included Realvalle Entrecot de vacuno, approximately 300 g at 7.49 EUR, and Realvalle Solomillo de ternera, approximately 250 g at 9.95 EUR.

Exact product pages can expose stable product paths and multiple images. Example:
https://www.lidl.es/p/la-bien-pinta-vino-blanco-d-o-rueda-verdejo/p11037304

Decision: Lidl should serve both as a retailer evidence source and a cheap retailer-first discovery surface. A retailer award badge is a discovery hint; when possible, the independent award authority must still verify the award semantics. Never transfer Lidl Great Britain or Lidl Ireland results to Lidl España merely because a private-label name matches.

#### ALDI España

Current exact ALDI pages expose a stable numeric product ID, exact name, package, current price and multiple images. They may also state the award.

Observed examples:
- LA TABLA Queso curado, 300 g, 3.35 EUR, explicitly described as Super Gold at World Cheese Awards:
  https://www.aldi.es/producto/queso-curado-181600.html
- LA TABLA Queso de oveja ahumado V de Navarra, 250 g, 4.29 EUR in the observed offer, explicitly described as bronze:
  https://www.aldi.es/producto/queso-de-oveja-ahumado-v-de-navarra-601233500.html

Decision: technically strong for exact-SKU price/photo verification. The competition authority should remain preferred for medal semantics. Preserve geographic price caveats published by ALDI.

#### Consum

Consum is one of the best technical retailer surfaces found.

Official ecommerce pages expose:
- stable Código producto;
- often EAN;
- exact volume/package;
- current price and unit price;
- product images.

Observed examples:
- CONSUM AOVE 0.5 L, code 7414787, 3.60 EUR;
- CONSUM ECO AOVE 0.5 L, code 7304397, EAN 8414807543455, 4.75 EUR;
- CONSUM Gouda tierno 350 g, code 7419021, EAN 8414807557421, 2.82 EUR.

Decision: use Código producto as stable retailer identity and EAN, when present, as the strongest cross-source product key. Consum is ready for an enrichment adapter even if award discovery still comes from OCU or a specialist competition.

#### Carrefour España

The public Carrefour supermarket surface renders product names, package variants, prices and images and asks for a postcode to resolve local availability.

A current Carrefour Extra AOVE category exposed several different sizes and variants:
https://www.carrefour.es/supermercado/la-despensa/aceites-y-vinagres-carrefour-aceite-de-oliva-virgen-extra/F-1y9wiZ10siZp646/c

Critical trap: Carrefour.es also contains marketplace products sold by third parties. A marketplace card is not evidence that a product is a Carrefour supermarket shelf item.

Decision: restrict to the supermarket surface plus a configured postcode/store context; reject third-party marketplace seller cards; prefer exact EAN/REF or another stable first-party product ID; include package size in identity.

#### Masymas / Juan Fornés Fornés

The masymas name is used by several independent supermarket businesses. For this project the target is the Valencian/Murcian chain operated by Juan Fornés Fornés, S.A.

Official online store:
https://tienda.masymas.com

Official FAQ:
https://masymas.com/es/index.php?catid=11&id=135&option=com_content&view=article

The FAQ states that product details can be viewed without registration and that online products use the same prices, offers and promotions as physical Masymas stores.

The current shop is JavaScript-driven. This research pass did not yet prove a stable anonymous JSON product contract.

Alteza is a shared distribution/private-label brand. An award for an Alteza product alone does not prove that the same SKU is currently sold by Juan Fornés.

Decision: keep Masymas in scope because it is locally relevant and has a real online catalogue. Before coding, perform one bounded browser-free network/API probe. Require an exact Juan Fornés SKU/EAN/current product card before saying that an awarded Alteza item is currently available there. Never substitute another masymas company's catalogue.

#### DIA España

DIA has an unusually useful current award surface:
https://www.dia.es/l/productos-premiados-dia

Observed 2026 examples:
- Burrata fresca Dia Selección Mundial 150 g — 2.19 EUR;
- Tarta de queso Dia Caprichoso 250 g — 2.75 EUR.

The page explicitly ties the products to Sabor del Año 2026 and current ecommerce sale.

Decision: add DIA to the retailer set. Use the page for exact retail identity/current sale and as a discovery hint; verify award semantics through the award authority or another authoritative result source before registering an automated award adapter.

#### Alcampo / Auchan — researched, then excluded

Official Alcampo ecommerce was technically viable: the research found stable
numeric product paths, price/unit price, package, image and legal product
details. The observed Auchan Salmorejo 1 L card also provided a clean example
of joining an OCU result to an exact retailer product.

However, technical suitability is not enough for this local feature. Alcampo
has low practical relevance for the Guardamar audience because there is no
nearby store that most residents can conveniently use.

Decision: **exclude Alcampo / Auchan from the active retailer scope**. Do not
use it for runtime private-label matching, retailer enrichment, current-price
refresh, photos or award publication. Keep this section only as historical
research so the source is not re-evaluated from scratch later.

### Award-source vertical review

#### OCU

Status: implemented source adapter; retain and enrich.

The 7 July 2026 Salmorejo report proves that OCU can support a much richer deterministic article. It explicitly supplies:
- 30 products;
- labeling and composition review;
- OCU health-scale evaluation;
- blind professional chef tasting;
- appearance, smell, taste and texture dimensions;
- exact result and score;
- professional-tasting distinction;
- health classification;
- source-published price.

A source-specific renderer can use those facts without a language model.

#### Sabor del Año

Status: high-value source family; authoritative deterministic discovery contract still needs to be proven before registration.

The 2026 result set includes direct supermarket products from Lidl and DIA. Public result reporting records 89 recognised food products in 2026, including Lidl fresh salmon, Lidl entrecôte and tenderloin, DIA natural yoghurt, DIA Selección Mundial burrata and DIA Caprichoso cheesecake.

Semantic rule: this is consumer sensory recognition. Do not rewrite it as an objective category championship or first place unless the award authority explicitly publishes such a rank.

Retailer pages are excellent identity/current-sale evidence but should not become the sole award authority when a dedicated award result is available.

#### World Cheese Awards / Guild of Fine Food

Status: high-priority future source; 2026 adapter must wait.

Official dates:
- judging: 12 November 2026 in Córdoba;
- Gold, Silver, Bronze and Super Gold results: public directory within 24–48 hours;
- trophy winners: 16 November 2026.

Therefore no 2026 parser should be shipped on 25 September 2026. Probe and implement against the real November result format.

Do not confuse World Cheese Awards with World Championship Cheese Contest.

#### World Championship Cheese Contest 2026

Status: current source candidate.

Official 2026 Top 20 includes class 114 Hard Mixed Milk Cheeses, Seleccion Tostado Mixed Milk Cheese Extra Aged, Queserías Entrepinares, Valladolid.

This proves current Spanish supplier relevance but does not prove a Mercadona SKU. The complete result database needs a bounded source probe and exact retail evidence.

#### GourmetQuesos 2026

Status: strong Spanish cheese source candidate.

Official 16th GourmetQuesos data records more than 800 samples, 65 judges, two qualifying phases, 20 categories and 60 finalists. Judging includes rind, colour, texture, aroma, flavour, aftertaste and persistence.

This is excellent rich-article context when an exact winner can be joined to an exact supermarket SKU.

#### MUNDUS VINI

Status: technically strong wine source candidate.

Official result cards expose tasting edition, medal, submitter, country, wine category, quality level, denomination, vintage, alcohol, grape variety, bottle volume and recommended retail price.

A current 2026 example submitted by Lidl Stiftung is 2025 Hacienda Uvanis Tinto Joven, MUNDUS VINI Summer Tasting 2026, DO Navarra, Garnacha, 0.75 L, RRP 4.99 EUR.

Important rule: submitted by Lidl Stiftung does not prove current sale in Lidl España. A Spain-specific current Lidl card must match the exact wine, especially vintage, denomination and bottle size. Wine must never be matched only by label-family name.

#### Great Taste

Status: broad future source, second wave.

Guild of Fine Food publishes searchable Great Taste results. The directory includes retailer/private-label products from multiple countries.

Decision: accept only exact Spain retail SKU/EAN/current listing; never infer Lidl España or ALDI España availability from a UK/Ireland result.

#### NYIOOC World Olive Oil Competition

Status: promising AOVE source; exact retail match required.

The 2026 official NYIOOC news surface records a Gold for Casa Juncal from Aceites Oro Bailén Galgón 99 and identifies it as a medium-intensity Picual AOVE.

This becomes a supermarket article only when the exact award-winning commercial product/variant is proven to be the same current retailer SKU. Supplier relationship alone is insufficient.

#### MAPA — Alimentos de España Mejores Jamones

Status: authoritative vertical source candidate.

The Ministry's 2026 results record 51 samples and winners including Jamón Serrano 24 - Monte Nevado and Jamón de bellota 100 % ibérico Guillén. The official method uses expert sensory panels and separate categories.

This can create rich editorial context but still needs exact retail mapping before naming a supermarket.

#### MAPA — Alimentos de España AOVE

Status: authoritative award, unsafe for automatic supermarket-SKU transfer.

The 2025–2026 competition admits bulk AOVE from a homogeneous lot of at least 10,000 kg and uses organoleptic plus physical/chemical evaluation.

Permanent negative rule: a winning mill/producer is not evidence that every supermarket bottle produced by that company won. A supplier relationship must never transfer this award to a retail SKU without explicit commercial identity.

#### Producto del Año — Marca Distribuidor

Status: useful watch source; stable official scheduled result surface still needs validation.

The 2026 distributor-brand results include retailer brands such as Lidl and Alteza. This is attractive because retailer identity can be explicit in the award.

For Alteza, exact Juan Fornés retail evidence remains mandatory because the label is shared across a wider purchasing/distribution structure.

### Award-to-retail identity gate

Award evidence and retailer evidence are separate authorities.

Accept a join, strongest first, when:
1. exact EAN/GTIN matches;
2. exact retailer SKU/product ID is explicitly tied to the awarded commercial product;
3. exact commercial name plus variant plus package/vintage plus maker match, no competing same-name SKU exists, and category-specific identity rules pass.

Reject when evidence is only:
- manufacturer/supplier equality;
- brand equality;
- retailer relationship with the producer;
- product-family name;
- fuzzy text similarity;
- same visible name with multiple SKUs;
- same private-label brand in another country;
- Carrefour marketplace listing from a third-party seller;
- bulk/lot award with no explicit commercial retail mapping.

No LLM or generic fuzzy matcher may override these rules.

### Category-specific identity

Wine:
- exact label/cuvée;
- vintage when stated;
- DO/IGP/DOP or equivalent;
- bottle size;
- grape/variant where needed;
- EAN preferred.

Cheese:
- exact commercial name;
- milk/type;
- maturation/age;
- flavour variant;
- format/weight when relevant;
- maker.

AOVE:
- exact commercial brand/variant;
- cultivar, campaign or style when part of award identity;
- producer/bulk-lot award alone is insufficient.

Jamón/cured meat:
- exact commercial name;
- ibérico percentage;
- feed/category such as bellota or cebo;
- recognised quality figure;
- cured-age/product variant;
- whole piece vs sliced format when the award distinguishes it.

Fresh meat/fish:
- preserve the range/cut scope the award actually names;
- do not pretend one tray size won when the award covers the broader range.

Olives:
- exact variety/filling/salt/flavour variant and package when available.

### Current price lifecycle

Because the shared queue may delay publication for several days, do not freeze a current retailer price at award-discovery time.

Preferred flow:
1. award adapter proves the award;
2. retailer evidence resolves an exact stable retailer product ID/EAN;
3. immediately before publication, perform one bounded exact-SKU refresh;
4. if still current, use refreshed price and availability;
5. if price cannot be safely refreshed, omit the current-price sentence;
6. never substitute a search-engine, aggregator or stale cached price.

When a retailer varies price/stock by store or postcode, preserve that context. Use one explicit configured Guardamar retail context, not device/user geolocation.

Retail identity may be necessary to claim that a third-party award product is currently sold by a chain. Live price itself remains optional.

### Product photos

Exact product images are technically exposed by several current retailer surfaces:
- Lidl;
- ALDI;
- Consum;
- Carrefour supermarket;
- DIA;
- Mercadona after exact SKU resolution.

Masymas still requires the internal store contract probe.

Rules:
- only an exact matched SKU/product;
- allowlisted HTTPS retailer or award-authority media host;
- bounded image content type and size;
- no Google/image-search result and no generic brand image;
- if exact image is unavailable, publish text-only.

Technical accessibility does not automatically grant republication rights. Before Telegram media is enabled for a retailer, record a terms/licence review for that media source. If the required reuse is not permitted or is unclear, retain the source link and publish text-only.

Photo failure must never invalidate a verified award article.

### Rich deterministic editorial contract

The current ProductAwardCandidate is too narrow to consistently produce the desired article quality.

Future source records should be able to retain a small reviewed set of verified facts such as:
- award body and edition/year;
- exact medal/result/tier;
- category/class;
- score/points;
- number of compared products or entries;
- number/type of judges or consumer testers;
- judging method;
- source-backed standout result;
- source-backed nutrition/quality classification;
- exact product identity attributes;
- producer/maker;
- source-published study price;
- separately refreshed current retailer evidence.

Do not add a free-form generic prose extractor. Each adapter should expose only source facts whose semantics are known.

Renderer strategy:
- OCU: comparison size, method, score, tasting result, health-scale result and exact current retail price when safely matched;
- Sabor del Año: consumer sensory recognition and exact awarded range/product, without inventing category ranking;
- cheese contests: medal/place/class, competition scale and published judging criteria;
- MUNDUS VINI: medal/edition, vintage, DO, grape and bottle identity;
- MAPA jamón: official category, sample scale and expert sensory process;
- AOVE: exact commercial award identity and cultivar/style only when tied to the retail product.

The renderer remains deterministic. A small source-renderer registry is cheaper and safer than runtime LLM editorial writing.

### Discovery architecture

Use two complementary directions while retaining one shared queue.

Award-first:
- OCU;
- World Cheese Awards once 2026 results exist;
- World Championship Cheese Contest;
- GourmetQuesos;
- MUNDUS VINI;
- NYIOOC;
- suitable MAPA awards;
- Great Taste later.

Retailer-first:
- Lidl España Productos premiados;
- DIA Productos premiados;
- ALDI exact product/award editorial pages.

Retailer-first pages provide a small already-relevant candidate set. The bot then verifies the award against its authority before queue eligibility. This avoids scanning huge global directories for thousands of irrelevant products.

### Recommended implementation sequence

1. Keep OCU as the first production adapter and complete its production-device read-only preview before deployment.
2. Before production state exists, broaden the model so award identity and retail evidence are separate and private_label is no longer universal.
3. Add retailer evidence adapters incrementally, starting with the clearest current contracts: Consum, ALDI, Lidl, DIA, then Carrefour with a marketplace guard.
4. Perform dedicated bounded probes for Mercadona exact product JSON/API and Masymas / Juan Fornés internal JSON/API.
5. Enrich the OCU fact model and renderer so it can create article-depth deterministic copy.
6. Add one genuinely new award family only after a live current source probe. WCCC/GourmetQuesos and MUNDUS VINI are current candidates. World Cheese Awards 2026 waits for November.
7. Add Telegram photo delivery only after exact media identity and source-specific terms/reuse review.

Do not create retailer-specific cron jobs. Catalogue reads occur only while verifying a candidate or immediately before publication.

### Architecture re-review

ADR 0083 remains correct at the engine level:
- one source-adapter award engine;
- one queue;
- per-source first-run baseline;
- maximum one article per day;
- no universal LLM parser;
- source-native award event identity;
- retail enrichment must never rewrite award identity.

The assumption that every candidate is a private label is too narrow.

The durable flow is:

award evidence -> exact retail identity/evidence -> shared queue -> publication-time exact-SKU refresh -> rich deterministic renderer

Award identity remains stable when price, stock or photo changes.

A price/photo failure degrades the article instead of fabricating a replacement. Failure to prove that the awarded product is the same retail product must fail closed for any claim that it is currently sold by that chain.

### Verified URLs from the horizontal pass

Award-authority/result surfaces:

- OCU 2026 Salmorejo report:
  https://www.ocu.org/alimentacion/platos-preparados/informe/salmorejos
- OCU Salmorejo methodology:
  https://www.ocu.org/alimentacion/platos-preparados/asi-analizamos-salmorejos
- World Cheese Awards 2026 information and dates:
  https://gff.co.uk/for-producers/world-cheese-awards/
- World Cheese Awards 2026 result publication terms:
  https://gff.co.uk/world-cheese-awards-policies/terms-conditions/
- World Championship Cheese Contest 2026 Top 20:
  https://worldchampioncheese.org/2026-wccc-top-20-finalists/
- GourmetQuesos 2026 official results/context:
  https://www.gourmets.net/salon-gourmets/2026/catalogo-expositores/grupo-gourmets/16-gourmetquesos-campeonato-de-los-mejores-quesos-de-espana-2026
- MUNDUS VINI results:
  https://www.meininger.de/en/tastings/mundus-vini/results
- MUNDUS VINI current Lidl-submitted Spanish example:
  https://www.meininger.de/en/wine/awarded-wines/2025-hacienda-uvanis-tinto-joven-0
- NYIOOC current Casa Juncal result/news:
  https://news.nyiooc.org/release/aceites-oro-bailen-galgon-99-wins-four-golds-and-a-silver-at-2026-nyiooc
- MAPA 2026 jamón award:
  https://www.mapa.gob.es/en/alimentacion/temas/promo-alimentos/premios-alimentos/ultima_edicion_jamones
- MAPA 2025–2026 AOVE competition:
  https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/ultima-campana-aceites

Retailer evidence/discovery surfaces:

- Lidl España awarded products:
  https://www.lidl.es/c/premiados/a10092875
- Lidl exact wine example:
  https://www.lidl.es/p/la-bien-pinta-vino-blanco-d-o-rueda-verdejo/p11037304
- ALDI exact Super Gold cheese example:
  https://www.aldi.es/producto/queso-curado-181600.html
- ALDI exact bronze cheese example:
  https://www.aldi.es/producto/queso-de-oveja-ahumado-v-de-navarra-601233500.html
- Consum exact product/EAN example:
  https://tienda.consum.es/es/p/aceite-de-oliva-virgen-extra-ecologico/7304397
- Carrefour supermarket AOVE category:
  https://www.carrefour.es/supermercado/la-despensa/aceites-y-vinagres-carrefour-aceite-de-oliva-virgen-extra/F-1y9wiZ10siZp646/c
- Masymas / Juan Fornés FAQ:
  https://masymas.com/es/index.php?catid=11&id=135&option=com_content&view=article
- Masymas / Juan Fornés online shop:
  https://tienda.masymas.com
- DIA 2026 awarded products:
  https://www.dia.es/l/productos-premiados-dia
Excluded-retailer historical evidence:

- Alcampo / Auchan was technically verified during research but is intentionally
  out of scope for Guardamar-local product-award publication because of low
  practical local accessibility.

Discovery-only evidence that is not yet approved as a scheduled award authority:

- 2026 Sabor del Año result reporting:
  https://www.foodretail.es/food/sabor-del-ano-2026distingue-a-89-productos-de-alimentacion.html

Do not silently promote a discovery-only article into a production authority.
A future implementation must still prove the responsible award body's own
stable public result contract.

### Photo-rights follow-up

The technical ability to fetch an exact product image is not sufficient to
republish it in Telegram.

Current legal/terms checks on 25 September 2026 found explicit restrictions on
copying, reproduction, distribution or public communication of site content
without prior permission for several target retailers:

- Lidl España;
- Consum;
- Carrefour España;
- DIA España;
- Masymas / Juan Fornés Fornés.

Juan Fornés' own legal notice states that the information, graphic design and
code are protected and expressly excludes reproduction, distribution,
transformation and public communication of all or part of the site content.
Its app terms likewise reserve exploitation rights in photographs and other
content.

The safe product decision is therefore stronger than the earlier generic
"review terms before use" rule:

- retailer product photos are **disabled by default**;
- technical image URLs may still be inspected for identity verification;
- a Telegram product photo is enabled only for a source where an explicit
  licence, permission, press/media asset policy or other sufficiently clear
  reuse right has been documented;
- uncertainty means text-only publication;
- never copy a retailer product image merely because the HTTP URL is public.

This does not affect use of factual catalogue data such as exact product
identity, package and current price when obtained through a permitted public
surface.

### Masymas domain/company negative test

Do not treat an arbitrary site containing the masymas name as evidence for the
target Valencian/Murcian retailer.

A live investigation found that supermasymasonline.com belongs to HIJOS DE
LUIS RODRÍGUEZ S.A. in Asturias, not JUAN FORNÉS FORNÉS S.A. A current Alteza
product found there therefore cannot establish current availability in the
Guardamar-area Masymas chain.

The target company identity must be Juan Fornés Fornés, S.A.; its official
online-store and masymas.com surfaces are the accepted starting point.

### Final no-change cost rule

The horizontal expansion must not become eight daily catalogue scans.

Normal discovery remains award-first or retailer-award-list-first. Retailer
catalogues are queried only when a relevant candidate exists:

1. discover a bounded award/result item or a bounded retailer award lead;
2. verify the independent award semantics;
3. resolve one or a few exact retailer SKU candidates;
4. enqueue only after the retail relationship can be stated correctly;
5. immediately before publication, refresh only the already-resolved exact SKU
   for current price/availability.

Thus a quiet day should add almost no retailer catalogue traffic. No per-retailer
cron, full catalogue crawl, browser session or continuous stock monitor is
introduced.

### Same-day price volatility proof

DIA provided a useful live proof that award discovery price must not be treated
as publication price.

The official 2026 awarded-products page and exact product cards expose stable
numeric product IDs:

- Burrata fresca Dia Selección Mundial 150 g:
  `/quesos/fresco/p/263576`;
- Tarta de queso Dia Caprichoso 250 g:
  `/yogures-y-postres/postres-tradicionales/p/307308`.

Within the same research day, fresh indexed/opened representations already
showed changed prices for these exact products. The specific values are not a
durable project constant; the important result is that exact retail price can
change between discovery and later rendering even when product identity is
stable.

This directly validates ADR 0084's publication-time exact-SKU refresh.

### OCU is already horizontal across retailers

OCU must not be modelled as a Mercadona-specific source.

Current 2026 OCU material includes, among other examples:

- Hacendado / Mercadona Salmorejo as Mejor del Análisis;
- Carrefour Extra Black nata y chocolate negro as Mejor del Análisis;
- current whole-milk comparison material with multiple supermarket products.

OCU also contains Auchan / Alcampo results, but the project deliberately ignores
them because Alcampo is outside the locally useful retailer scope.

OCU exact comparator cards can expose strong retail identity facts such as EAN,
format and manufacturer. These surfaces are useful for deterministic product
identity, but award labels shown inside generic "alternatives" widgets must not
be attributed to the page's primary product. The current report parser's local
evidence rule remains correct.

Future OCU expansion should evaluate comparator/category surfaces separately
instead of weakening report-local parsing.

### Current retailer-photo legal evidence

The photo default-off policy is now supported by direct legal pages, not only a
general copyright assumption.

- Lidl España's legal notice prohibits reproduction, distribution and public
  communication of site content for commercial purposes without authorization.
- Consum's shop legal notice prohibits reproduction, distribution, public
  communication, retransmission, copying and redistribution except personal
  and private use.
- Carrefour states that no licence is granted and specifically reserves
  alteration, exploitation, reproduction, distribution and public
  communication unless expressly authorized.
- DIA's current legal notice gives only strictly private use and prohibits
  copying, reproduction, public communication, transformation or distribution
  for public or commercial purposes without prior written authorization.
- Masymas / Juan Fornés' legal notice expressly excludes reproduction,
  distribution, transformation and public communication of protected site
  content.

Therefore the project must not interpret "we can fetch the image" as "we may
send the image to Telegram".

### Pre-implementation code re-review

The wider research was compared back against the current Python implementation
before any production deployment.

The shared operational model is still good, but the current code is not yet
compatible with ADR 0084 and must remain draft.

Required pre-production changes:

1. `ProductAwardCandidate.private_label` is mandatory. It must no longer be
   universal because a valid award product may be a third-party listed brand or
   a retailer-exclusive product.
2. The generic non-OCU renderer currently says every future product is
   `собственной марки`. That wording becomes factually wrong for ordinary
   listed brands and must be relationship-aware.
3. Stable retail identity needs its own record: retailer, relationship type,
   exact product ID and/or EAN, product URL, package/variant qualifiers and the
   configured retail context needed for a later exact refresh. Live price and
   photo URL must not become award event identity.
4. Rich verified source facts need a small typed/source-specific context so
   OCU, cheese, wine, jamón and consumer awards can render article-depth copy
   without generic free-form extraction.
5. Publication needs one optional exact-SKU retailer refresh before rendering.
   It must not search the catalogue by fuzzy product name at send time.
6. The common `_result_priority()` currently imposes one global ranking
   (`trophy > super gold > gold > silver > bronze > OCU`). This does not scale
   safely to unrelated award semantics such as Great Taste stars, category
   places, OCU value labels and wine competition distinctions. Canonicalisation
   of multiple results for the same source event belongs at the source adapter
   boundary; the shared core should not invent a universal award hierarchy.
7. Source discovery remains capped and bounded. Large global directories such
   as Great Taste or WCA should therefore be filtered using a source-native
   query/retailer-first lead rather than converted into a broad catalogue crawl.

Things that should **not** be added:

- a generic retailer search framework;
- daily scans of all eight supermarket catalogues;
- a database;
- an image cache;
- a browser;
- fuzzy matching;
- LLM product matching or prose generation;
- one queue or cron per retailer/award body.

Because no production product-award state has been established yet, evolving
the serialized candidate/state schema now is cheaper and safer than maintaining
a compatibility layer for an unused schema.

## Implementation status — 26 September 2026

The ADR 0084 foundation has now been implemented on draft PR #195 without
adding any speculative retailer crawler.

Implemented:

- `ProductAwardCandidate` no longer assumes every product is a private label;
- explicit `RetailEvidence` distinguishes `private_label`, `exclusive`
  and `listed` relationships and can retain exact retailer product ID, EAN,
  exact product URL and variant evidence;
- award event identity remains source-native and independent of retail price,
  stock and media;
- state schema is version 6; no compatibility layer was added because the
  feature has not yet established production state;
- the shared core no longer ranks unrelated award vocabularies;
- OCU owns its own `Mejor del Análisis` vs `Compra Maestra` precedence;
- OCU coverage includes DIA private-label names in addition to the earlier
  locally relevant allowlist, while Alcampo / Auchan is intentionally ignored;
- labels identical to retailer names such as Carrefour or DIA require separate
  product-brand evidence and are not accepted merely because the retailer name
  appears in parentheses;
- OCU editorial facts are separated into report-global method facts and
  product-local distinctions so one product's tasting/quality statement cannot
  leak to another result;
- the deterministic renderer distinguishes private label, exclusive and listed
  products;
- publication-time retail enrichment now accepts a list of exact package
  variants rather than one chosen price, so every verified package/price/unit
  price can be shown without transferring an award to another SKU;
- producer facts require an explicit production country; city/region remains
  optional additional context;
- headlines now lead with product + supermarket + award/result and keep numeric
  score in the article body;
- repeated award methodology renders in Telegram HTML
  `<blockquote expandable>` rather than occupying the visible daily post;
- OCU publication now requires overall/global score >=85/100 and sorts its own
  eligible candidates by that native score; high partial subscores cannot pass
  the gate;
- the official WCCC 2026 Top-20 page is now registered as the second award
  adapter, restricted to the reviewed 2026 contract rather than guessing future
  URL/shape compatibility;
- one exact WCCC-to-retail join is implemented: class 114
  `Seleccion Tostado Mixed Milk Cheese Extra Aged` by
  `Queserías Entrepinares S.A.U.` -> Mercadona SKU `50952`,
  EAN `8480000509529`;
- WCCC Top-20 is treated as an exceptional source-native tier even without a
  public numeric score on the Top-20 page;
- Mercadona exact-SKU refresh is implemented for the reviewed Guardamar
  warehouse context and validates product ID, EAN, brand, supplier, published
  status and official share URL before returning current package/price;
- current retail price is now mandatory for public delivery: refresh failure
  yields no publication and does not reserve the daily slot;
- bounded publication scan checks up to four queued items, so one temporarily
  unavailable/delisted product cannot block later verified candidates; skipped
  items remain queued and are not marked published;
- delivery queue, per-source baseline and at-most-once Telegram semantics remain;
- the former one-item-per-day product policy is superseded by category-first
  selection and a three-local-day public delivery cooldown.

The feed is intentionally **at most one selected category winner every three
local calendar days**, not a quota. If no category has an eligible ranked
retail match, publication stays silent. Future adapters must preserve the
source's real ordering and must not invent podium positions from unordered
finalists or equal medal tiers.

Deliberately **not** implemented yet:

- no generic retailer catalogue search;
- no continuous or daily scans of the six in-scope retailers;
- Masymas still has no parser before its exact browser-free contract is
  separately proven;
- Mercadona retail refresh currently supports only exact reviewed product IDs;
  it does not search the catalogue or discover related package sizes;
- no retailer product-photo publication; the default remains text-only unless a
  source-specific reuse right is documented;
- broader WCCC class/result coverage is not implemented; only the reviewed
  2026 Top-20 Entrepinares/Mercadona join is active.

Validation on the final functional head before removing the temporary
branch-only workflow:

- Python compileall: passed;
- product-award modules: **69 tests passed**;
- merged current `main` before final validation; PR mergeability was restored without dropping unrelated event/digest changes;
- complete repository suite: **1414 tests passed**;
- temporary validation workflow was removed from the final diff.
- the seven-day starter preview passed live exact-retail refresh for every
  candidate; day 3 is NALTROS Brut at ALDI, live-reviewed at 0.75 l,
  3.15 EUR and 4.20 EUR/l; the six cheese candidates also retained their
  previously reviewed exact Mercadona offers.
- final review also tightened Valle retail identity: the current Mercadona
  supplier list must still contain Valle de San Juan itself; a distributor or
  packer alone can no longer preserve the award-to-retail join.
- live `product-awards-preview` on 26 September 2026 produced the reviewed WCCC Top-20 Entrepinares / Mercadona SKU 50952 article with a fresh official Mercadona offer: approximately 370 g, 6.19 EUR, 16.74 EUR/kg.

The next broader retailer implementation should remain one source-specific
contract at a time, not a generic catalogue framework. Consum remains the
strongest clean candidate because its public catalogue can expose a stable
product code and often EAN; Lidl and DIA are also strong candidates. Mercadona
and the one reviewed ALDI NALTROS product now have browser-free exact-product
refreshers. Masymas still needs its dedicated browser-free contract probe.
Alcampo / Auchan remains intentionally excluded for local-utility reasons.



### Starter-pool extension — Semicurado, 26 September 2026

The reviewed launch pool was extended from five to six days after a direct
Mercadona `alc1` probe resolved Valle de San Juan's WCCC 2026
`Semicurado — 97.40` to current SKU `11672`:

- retail name: `Queso semicurado de oveja Hacendado cortado en cuñitas`;
- EAN: `8402001028861`;
- legal product type: pasteurized sheep's-milk semicurado;
- suppliers include `Valle de San Juan S.L.`;
- current reviewed offer: approximately 280 g, 4.14 EUR, 14.80 EUR/kg;
- published=true, no `unavailable_from`, no unavailable weekdays.

This join is stronger than the unrelated Entrepinares mixed-milk semicurado
SKUs (50943/50944/50945/50946), which are explicitly excluded from the Valle
mapping. The seed keeps source-backed product/tasting/composition facts and
does not copy unverified nutrition values from third-party price trackers.



### Starter-pool extension — NALTROS Brut, 26 September 2026

The launch pool was diversified from six cheese posts to seven days by adding
one exact current ALDI cava candidate after the first two cheese posts.

Award evidence:

- OCU press release:
  `https://www.ocu.org/organizacion/prensa/notas-de-prensa/2025/cavas191225`;
- 25 D.O. Cava products compared;
- NALTROS Brut (ALDI) global score: **94/100**;
- OCU places it among the three standout cava and describes the expert tasting
  panel as the most important part of the comparison;
- the analysis also checks alcohol, sugar, volatile/total acidity, sulfites and
  other additives;
- exact OCU product page:
  `https://www.ocu.org/alimentacion/vino/comparador/naltros-aldi-brut/210/124487`,
  identifying D.O. Cava and winery Jaume Serra.

Retail evidence:

- exact ALDI card:
  `https://www.aldi.es/producto/cava-brut-190300.html`;
- browser-free raw HTML contains Next.js `__NEXT_DATA__`;
- product payload lives at the reviewed
  `props.pageProps.apiData` JSON-string field;
- reviewed identity: `brandName=NALTROS ®`,
  `salesUnit=0,75 l unidad`, `KVArticleNumber=1903`;
- availability flags are explicit;
- reviewed live offer on 26 September 2026: 3.15 EUR / 0.75 l and 4.20 EUR/l.

Implementation decision: keep this as one exact source-specific retail
refresher and a reviewed launch-seed award fact. Do not generalize it into a
full ALDI catalogue crawler.

#### AOVE candidate rejected for the launch seed

Mercadona's official category/product APIs cleanly resolved Hacendado AOVE
1 l to SKU `4740`, EAN `8402001001185`, current 4.45 EUR / 4.45 EUR/l,
with current availability. The exact OCU card `109008` also confirms
Hacendado AOVE and a 1000 ml format.

However, the anonymous exact-product OCU HTML hides the product's own quality
score behind `Ver resultados`. The apparent 89/100 Compra Maestra association
can be inferred from surrounding comparator data and matching reference price,
but it was not directly tied to exact product ID `109008` in the reviewed
public product block. Under the fail-closed identity rule this is insufficient,
so AOVE is deliberately **not** included in the starter seed.


## Category-first redesign — 26 September 2026

The earlier launch-pool idea is superseded before production. The user-facing
feed now answers a narrower question: **what is the best currently purchasable
product in each reviewed category among six major supermarket chains?**

Active retail scope:

1. Mercadona;
2. Carrefour España supermarket;
3. ALDI España;
4. Lidl España;
5. DIA España;
6. Consum.

Masymas / Juan Fornés and Alcampo / Auchan are no longer active matching targets
for this feature. Keep their earlier research only to avoid repeating source
investigation.

### Selection algorithm

For each broad reviewed category and award edition:

1. take the source's explicit #1 result;
2. require the source-specific exceptional-quality gate (>=85 overall where a
   comparable 0-100 score exists);
3. attempt exact current retail identity in the six active chains;
4. if #1 has no exact current retail match, repeat for explicit #2;
5. if #2 fails, repeat for explicit #3;
6. if none of the explicitly ranked top three is currently sold in scope,
   produce no event for that category/edition.

Never manufacture a rank from unordered finalists, alphabetical result lists,
equal medal tiers or a retailer's own marketing order. If the authority
publishes only a category winner, there is no fallback #2/#3 unless another
authoritative ordered source contract proves them.

Only one selected product is retained per broad category/edition. Multiple
97-99 point cheeses from one contest no longer become consecutive public posts.

### Publication cadence

Discovery may continue daily when bounded and cheap. Public delivery changes
from daily to **at most once every three local calendar days**, measured from
the last confirmed Telegram delivery. This must be a state cooldown rather than
a `*/3` calendar schedule.

### Source/category suitability review

#### Cheese — strong overall podium source

World Championship Cheese Contest 2026 publishes a genuine overall podium:

1. Beemster Royaal Grand Cru — 98.68/100;
2. Appenzeller Purple Label — 98.45/100;
3. Alter Fritz — 98.41/100.

The contest had 3,375 entries. This is a clean implementation model for the
broad `cheese` category: test those exact three in order against the six
retailers. A lower-ranked Spanish cheese must not replace them merely because it
is easier to buy locally.

World Cheese Awards and GourmetQuesos remain useful evidence sources, but do
not automatically replace the WCCC broad-category podium. GourmetQuesos
publishes first/second/third within 20 cheese classes plus one absolute winner;
those class podiums should not be treated as 20 separate consumer categories
without an explicit future product decision.

MAPA's 2026 cheese awards publish one overall special winner plus winners in
five milk/style modalities. This is authoritative Spanish evidence but does not
provide a public overall #2/#3 fallback.

#### Extra-virgin olive oil — strong ranked source

EVOOLEUM 2026 exposes an ordered global Top 10 with numeric scores. The first
three are:

1. Di Molfetta Frantoiani di Coratina — 97;
2. Monini Monocultivar Coratina Bio — 96;
3. Oleum Hispania Nature Premium Pajarera — 96.

This is suitable for the broad `extra_virgin_olive_oil` category once exact
retail availability for ranks 1-3 is checked in the six chains.

MAPA's AOVE award is authoritative for Spain but its public result shows one
winner and two finalists per modality without ordering the two finalists.
Therefore those finalists must not be re-labelled as #2/#3. The existing
bulk-lot warning also remains: producer/lot success is not retail bottle
identity.

#### Wine — use consumer-meaningful styles, not one synthetic global wine rank

Bacchus 2026 had 1,540 labels and explicitly names Best White, Best Rosé, Best
Red and Best Sparkling wines. It also defines medal score bands (Grand Gold
>=93, Gold 89-<93, Silver 85-<89), but its public medal list does not establish
an ordered #2/#3 inside each style.

Therefore the safe initial wine taxonomy is style-based:

- `wine_red`;
- `wine_white`;
- `wine_rose`;
- `wine_sparkling`.

For each style, check the explicitly named best wine. Do not infer runner-up
positions from other Grand Gold wines unless the source later exposes a
reviewed ordered score contract.

MAPA 2026 independently names best red, white, rosé, sparkling and fortified
wine, but publishes only the winner of each modality. It can be a strong
winner-only source, not a fabricated three-place podium.

#### Jamón — two distinct consumer categories, winner-only source

MAPA 2026 publishes:

- best Jamón de Bellota Ibérico;
- best Jamón Serrano / other recognized quality figure.

Treat these as two separate consumer categories. The public result names the
winner, not ordered second/third places. Each category therefore checks one
winner only until an authoritative ranked fallback source is proven.

#### Table olives — source still unresolved

OLIVE JAPAN 2026 includes table olives, but its public structure is Premier,
Gold and Silver rather than a clean overall ordered top three for table olives.
It is not sufficient for the new strict podium algorithm.

Keep `table_olives` pending. Do not publish an olives category until a
credible source with an explicit winner or ordered podium and exact product
identity is validated.

### Consequence for the old starter seed

The seven-item reviewed starter sequence (five Valle cheeses, one Entrepinares
cheese and one ALDI cava) is **not production-valid under the new product
concept** because six of seven entries represent the same broad cheese
category.

Do not deploy or seed that queue. Its exact SKU and retailer research remains
useful evidence for future joins, but category selection must be recomputed from
the authoritative podium before any launch.


### Cross-source fallback inside one category

A broad category may have more than one authoritative award/ranking source.
Do not compare raw scores from unrelated competitions. Instead define an
ordered list of independent source contracts for the category.

Selection is sequential:

1. take source A and exhaust only its explicit #1 -> #2 -> #3 in that order;
2. each rank must pass the source-specific exceptional-quality gate and exact
   current retail verification in one of the six active chains;
3. if none of source A's eligible top three has a verified retail match, move
   to source B and restart at source B's #1;
4. never combine source A's #1 with source B's #2/#3 as if they formed one
   podium;
5. if a source publishes only a winner, test that winner once and then move to
   the next source contract if it has no verified target-retail match.

This preserves authority semantics while still allowing a consumer-relevant
fallback when a world/global podium is not sold through the six supermarket
chains.

Where two products are genuinely tied by the authoritative source, retain the
tie rather than manufacturing #1/#2. Prefer a candidate with a verified exact
current retail match. If several tied candidates have equally strong retail
evidence, preserve source order; do not invent a cross-source quality
tie-breaker.

### Current category matrix — 26 September 2026

#### READY — sparkling wine / cava

Primary Spanish-government source:

- MAPA 2026 names `Cuvée D.S. 2019` by Freixenet as Best Sparkling Wine.
- The reviewed public result exposes a winner only, not ordered #2/#3.
- No exact current first-party listing for that vintage was established in the
  six target supermarket chains during this pass.

Secondary consumer-ranking source:

- OCU analysed 25 D.O. Cava products.
- Three products tie at 94/100; the first named is `Naltros Brut (ALDI)`.
- ALDI currently exposes exact `NALTROS Cava Brut`, 0.75 l, at 3.15 EUR
  (4.20 EUR/l), with DOP Cava and current product details.

Decision: category is **READY** through the secondary OCU source after the
winner-only MAPA source yields no verified current retail match. Keep the tie
semantics; do not claim Naltros uniquely scored above the other 94-point cava.

Sources:

- https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados_vino
- https://www.ocu.org/organizacion/prensa/notas-de-prensa/2025/cavas191225
- https://www.aldi.es/p/cava-brut-190300.html

#### READY — gazpacho

OCU compared 39 refrigerated gazpachos. `Real Fooding` is explicitly
`Mejor del Análisis`, global score 90/100, and best in both professional
tasting and OCU's healthy-scale assessment.

Carrefour currently sells exact `Gazpacho fresco Realfooding sin gluten 1 l`
for 4.05 EUR / 4.05 EUR/l. The card identifies manufacturer
`CAÑA NATURE, S.L.U.` and country of origin Spain.

Decision: **READY**, rank #1 directly matches an active target supermarket.

Sources:

- https://www.ocu.org/alimentacion/platos-preparados/informe/gazpachos
- https://www.ocu.org/alimentacion/platos-preparados/asi-analizamos-gazpachos
- https://www.carrefour.es/supermercado/gazpacho-fresco-realfooding-sin-gluten-1-l/R-VC4AECOMM-339275/p

#### PENDING — tuna in olive oil

OCU's explicit high-quality order:

1. `Sal de Plata (ALDI)` — 86/100;
2. `Hacendado (Mercadona)` — 85/100.

Both pass the >=85 overall gate.

The exact current ALDI permanent product card for the reviewed Sal de Plata
olive-oil tuna format has not yet been proven. Because #1 is known by OCU to be
an ALDI product, absence of a convenient public card is not sufficient evidence
that it is no longer sold.

Fallback #2 is technically proven current in Mercadona Guardamar context:

- SKU `18002`;
- EAN `8480000180025`;
- `Atún claro en aceite de oliva Hacendado`;
- current pack: 6 x 80 g gross, 360 g drained;
- current reviewed price: 4.90 EUR;
- supplier `ESCURIS, S.L.`;
- ingredients: tuna, olive oil and salt;
- published=true; no current unavailability flag.

Decision: category remains **PENDING**, not READY for #2, until #1 is either
proved currently available (then select #1) or positively rejected as no longer
a current exact ALDI product. Do not demote #1 merely because one retailer is
harder to inspect technically.

Award source:

- https://www.ocu.org/organizacion/prensa/notas-de-prensa/2023/atunclaroaceiteoliva050623

Reviewed fallback retail URL:

- https://tienda.mercadona.es/product/18002/atun-claro-aceite-oliva-hacendado-pack-6

#### SKIP — broad cheese

WCCC 2026 overall podium:

1. Beemster Royaal Grand Cru — 98.68;
2. Appenzeller Purple Label — 98.45;
3. Alter Fritz — 98.41.

The contest had 3,375 entries. No exact current first-party listing for these
three cheeses was established in the six target chains.

MAPA's Spanish cheese award is a strong secondary authority but exposes one
overall special winner, `Cremositos del Zújar`, without an ordered broad
#2/#3 fallback. No exact current target-retail match was established for that
winner either.

Decision: broad `cheese` = **SKIP** for now. Previously researched Valle de
San Juan / Entrepinares supermarket cheeses remain useful retail/identity
evidence but must not replace a higher broad-category podium simply because
they are easier to buy.

#### SKIP — extra-virgin olive oil under strict broad ranking

EVOOLEUM 2026 overall top three:

1. Di Molfetta Frantoiani di Coratina — 97;
2. Monini Monocultivar Coratina Bio — 96;
3. Oleum Hispania Nature Premium Pajarera — 96.

No exact current first-party listing for any of these top three was established
in the six target supermarket chains.

OCU is a plausible secondary supermarket-oriented source and currently shows a
93/100 `Mejor del Análisis` among 23 olive oils, while Carrefour currently
lists products such as Oleoestepa. However the anonymous OCU public surface
reviewed in this pass did not expose a sufficiently strong exact
product-to-93/100 identity join. Do not infer the winner from surrounding cards
or prices.

Decision: AOVE = **SKIP/PENDING secondary source**, not production-ready.

Sources:

- https://www.evooleum.com/mejor-de-cada-categoria/
- https://www.ocu.org/alimentacion/aceite-oliva

#### SKIP — table olives

VINAC uses blind tasting and awards three best table olives, but the reviewed
public result does not establish an ordered #1/#2/#3 podium. Exact current
target-retail matches for the awarded recipes were also not established.

Decision: **SKIP** until a source exposes a real winner/podium with exact
commercial identity.

#### SKIP — jamón

MAPA 2026 names winners for Jamón de Bellota Ibérico and Jamón Serrano /
recognized-quality categories, but the public result does not provide ordered
#2/#3 fallback. Exact current target-retail sale of the winners was not
established.

Decision: both jamón categories = **SKIP** for now.

#### SKIP — low-score prepared-food categories

The quality floor remains active even when a target retailer appears in the
top results.

Reviewed examples rejected:

- tortilla de patatas: top overall quality in the reviewed OCU set is below
  85/100;
- torrijas: explicit top three exists and Mercadona is #2, but best overall
  quality is only around 69/100;
- prepared paella/rice: top global results are around the low 60s;
- sardines in olive oil: reviewed target-retail examples are in the 60s.

Do not publish a merely relative winner from a weak comparison.

#### SEASONAL WATCH — Turrón de Alicante

OCU's exact `De Nuestra Tierra (Carrefour) Turrón de Alicante` is
`Mejor del Análisis` at 85/100 and therefore passes the minimum gate.

The reviewed current Carrefour search did not establish the exact winner as a
currently sellable product in September. Historic Carrefour documents prove
the De Nuestra Tierra product family/EAN lineage but are not current stock
evidence.

Decision: **seasonal watch**, re-check exact Carrefour retail identity/current
price around the Christmas assortment before selecting the category.

### Current launch runway under category-first rules

Confirmed production-quality categories right now:

1. sparkling wine / cava -> NALTROS Brut at ALDI via OCU fallback;
2. gazpacho -> Realfooding 1 l at Carrefour via OCU #1.

Pending high-value categories:

- tuna in olive oil -> resolve current ALDI rank #1 before allowing Mercadona
  rank #2;
- Turrón de Alicante -> seasonal current-retail confirmation;
- AOVE -> exact secondary OCU winner identity;
- MAPA wine styles -> exact current retail check of winner-only products.

At a three-local-day cadence, the two READY categories provide only about six
days of launch runway. This is still too small for production seeding. Keep
researching until at least five independent broad categories are READY, then
implement category-level state/dedup and the three-day cooldown.


## Lightweight runtime architecture audit — 27 September 2026

The category-first research above is retained, but the earlier runtime POC is
not the implementation baseline.

The old draft branch reached roughly 2,768 lines in
`src/telegrambot/product_awards.py`, about 1,775 product-award test lines, a
separate discovery/publication cron pair, a persistent discovery queue,
per-source baselines, source-item seen state and a reviewed seven-item starter
seed. Those mechanisms solved the earlier "continuous award feed" design, not
the final product requirement.

The final requirement is narrower:

- publish at most one exceptional product every three local calendar days;
- choose by broad consumer category, not by whichever new award item happened
  to be discovered first;
- within one category, evaluate authoritative sources in an explicit priority
  order;
- exhaust the source-native #1/#2/#3 in that source before considering the next
  source;
- never mix ranks across competitions;
- only after a ranked award candidate is known, verify that the exact product
  is currently sold by Mercadona, Carrefour España, ALDI España, Lidl España,
  DIA España or Consum;
- refresh the exact current price immediately before publication;
- fail closed when exact retail identity or current price cannot be proven.

### Runtime consequence

A discovery queue is unnecessary. The cheapest production shape is one
short-lived daily command:

1. read the tiny state file;
2. if fewer than three local calendar days have passed since the last confirmed
   post, exit before making any network request;
3. start after the last successfully published category and inspect the reviewed
   category registry in deterministic order;
4. for each category, query source #1 and test at most its explicit top three;
5. only when none has an exact current retail match, move to source #2 and begin
   again from its #1;
6. once one exact current retail offer is proven, render and send one post;
7. record the category/edition/event only after confirmed Telegram delivery.

If no candidate is publishable, the run stays silent and does not consume the
three-day slot.

This removes the separate discovery cron, queue, source baselines, seen-item
ledger and starter-seed lifecycle. It also means a non-due day costs zero award
HTTP requests.

### Source catalogue, not autonomous web research

Production does not search the internet for new competitions. It contains a
small reviewed registry of known authoritative award/comparison sources.
Adding a new award family is an occasional code/research change.

Each source adapter is intentionally small and source-specific. It returns only
the source's explicit ordered podium (maximum three candidates), or one winner
when the authority publishes no ordered #2/#3. It may not infer missing ranks
from finalists, medal tiers, alphabetical lists or equal-score products.

This is the intended meaning of "the bot works automatically": once a source
and category are reviewed, the phone can read the current result, follow the
rank fallback rule, verify the exact supermarket offer and current price, and
publish without operator research.

### Retail lookup policy

Retail access is candidate-targeted, never a full catalogue crawl.

Preferred exact identity evidence remains:

1. EAN/GTIN;
2. exact retailer product/SKU ID tied to the awarded product;
3. exact commercial identity with every category-critical qualifier and no
   competing same-name SKU.

Retail adapters are added only for proven lightweight official contracts.
Browser/Playwright, OCR, search-engine lookup, fuzzy matching and LLM product
matching remain prohibited.

Reusable work from the POC is limited to concepts or small helpers that still
fit this model: bounded HTTP/host checks, exact Mercadona and ALDI offer
verification, exact retail identity records, deterministic rendering and
at-most-once Telegram send safety. The queue/discovery framework and reviewed
cheese starter seed are deliberately not carried forward.

### Activation gate

Do not install a production cron or publish this feature until at least five
independent broad categories are READY. As of the retained research matrix:

- READY: sparkling wine / cava -> NALTROS Brut / ALDI;
- READY: gazpacho -> Realfooding / Carrefour;
- PENDING: tuna in olive oil -> resolve Sal de Plata / ALDI #1 before allowing
  the proven Hacendado / Mercadona #2 fallback;
- cheese, AOVE, table olives and jamón remain non-ready under the strict broad
  category rules;
- Turrón de Alicante remains a seasonal watch.

The implementation branch should therefore remain documentation/research-only
until the five-category launch gate is met. This avoids building and testing
runtime paths for a feed that still lacks sufficient content runway.


## Launch-gate completion and expanded source catalogue — 27 September 2026

A fresh source re-check completed the minimum launch matrix without weakening the
category-first rules.

### READY — AOVE / extra-virgin olive oil

Primary source remains EVOOLEUM 2026; its reviewed overall podium does not have
an exact current match in the six target chains.

The secondary source is OCU's latest 23-product supermarket AOVE analysis. OCU's
official 27 December 2024 article explicitly says the ranking is led by
**AOVE Oleoestepa, DOP Estepa**. The product was laboratory-tested and the
analysis covers authenticity, oxidation/ageing, acidity and professional
sensory assessment.

Current exact retail evidence is Carrefour España supermarket:
`Aceite de oliva virgen extra Oleoestepa 1 l.`, D.O. Estepa, Oleoestepa
S.C.A., 1000 ml PET. The reviewed current card exposed 7.65 EUR / 7.65 EUR/l.

Decision: **READY** through source #2 after the EVOOLEUM top three fail the
current exact-retail gate.

Sources:
- https://www.ocu.org/alimentacion/aceite-oliva/informe/aceite-oliva-virgen-extra
- https://www.ocu.org/organizacion/prensa/notas-de-prensa/2024/aceite271224
- https://www.carrefour.es/supermercado/aceite-de-oliva-virgen-extra-oleoestepa-1-l/R-589802552/p
- https://www.oleoestepa.com/aceite-de-calidad/premios-y-reconocimientos/

### READY — coffee capsules

The reviewed 2024 OCU capsule study covers 29 Nespresso/Dolce Gusto products,
with laboratory chemistry/contaminant checks and an expert sensory panel.
The reviewed result table places **AROM'ARTE (DIA) Intenso** at 85/100, the
highest overall score in the Nespresso-with-caffeine group. OCU's exact current
product page still identifies the same 20-capsule, 108 g, Nespresso-compatible
product and marks it `Analizado en el laboratorio`.

DIA currently exposes exact SKU **273821** as
`Cápsulas de café intenso Dia Arom'arte 20 unidades`; the reviewed current
price is about 3.80 EUR (0.19 EUR/capsule).

Decision: **READY**. The immutable 2024 result is a reviewed source fact;
publication-time runtime must revalidate the exact OCU product identity and
the current DIA SKU/price rather than re-derive the historical ranking.

Sources:
- https://www.ocu.org/alimentacion/cafe/asi-analizamos
- https://www.ocu.org/alimentacion/cafe/comparador/arom-arte-dia-intenso/273/103038
- https://www.dia.es/cafe-cacao-e-infusiones/capsulas-compatibles-nespresso/p/273821

### READY — spirits / anís

MAPA's **Premio Alimentos de España Mejor Bebida Espirituosa con Indicación
Geográfica 2026** names one national winner:
**Anís Chinchón de la Alcoholera Dulce**, I.G. Chinchón, submitted/elaborated
by González Byass Distribución.

The commercial identity is unambiguous across current official retailer cards:
- Carrefour: `Anís Chinchón dulce 1 l.`, 35% vol, I.G.P. Chinchón,
  González Byass S.A.;
- DIA: `Anís dulce Chinchon 1 L`, current SKU **275359**, González Byass;
- Consum: `CHINCHON Anís Dulce Botella 1 L`, product code **7325533**.

Reviewed prices during the investigation were 13.79 EUR in Carrefour/DIA and
12.29 EUR in Consum. These are observations only; runtime must refresh one exact
offer immediately before publication.

Decision: **READY** and this is the fifth independent broad launch category.

Sources:
- https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados-bebidas-espirituosas
- https://www.mapa.gob.es/es/prensa/ultimas-noticias/detalle_noticias/el-ministerio-de-agricultura--pesca-y-alimentaci-n-otorga-el-premio-alimentos-de-espa-a-a-la-mejor-bebida-espirituosa-2026-a-an-s-chinch-n-de-la-alcoholera-dulce/fcb3ac3c-83ad-49a8-a35f-f187bb20d9ec
- https://www.carrefour.es/supermercado/anis-chinchon-dulce-1-l/R-538001406/p
- https://www.dia.es/cervezas-vinos-y-licores/cremas-licores-y-brandy/p/275359
- https://tienda.consum.es/es/c/bebidas/licores/anis/5315

### OCU admission guard: laboratory-tested products only

OCU's current methodology page now explains that products not physically
laboratory-tested may also receive AI-derived evaluations from objective
characteristics and technical results of related products.

For this feature, that is not equivalent evidence.

An OCU product may qualify only when its exact OCU product/result evidence
explicitly says **`Analizado en el laboratorio`** (or an equally explicit
OCU statement proves it belonged to the physical comparative test). AI-derived
OCU recommendations are ineligible for product-award publication.

`Mejor del Análisis` keeps its OCU-defined meaning: best of the products
compared.

Source:
- https://www.ocu.org/info/quienes-somos/nuestros-analisis

### Still PENDING / seasonal

**Tuna in olive oil:** unchanged. Sal de Plata / ALDI remains OCU #1 at 86/100,
and Hacendado / Mercadona #2 is technically current, but #2 cannot be selected
until the exact current Sal de Plata olive-oil SKU is found or #1 is reliably
shown to be unavailable.

**Turrón duro:** El Almendro 250 g is a strong OCU 85/100 route and Carrefour
already exposes the exact 250 g product, but the reviewed current card was
temporarily out of stock. Keep as seasonal watch and re-check in the Christmas
assortment.

### New high-quality source families

The following sources passed the authority/semantics screen and should remain
in the reviewed source catalogue for future category expansion. They do not
become production adapters until an exact current target-retailer candidate is
proved.

- **Great Taste / Guild of Fine Food.** The 2026 Supreme Champion is Entrepeñas
  Wagyu Beef Ham from Spain after more than 15,000 entries. Strong
  champion semantics; no current exact target-six retail match yet.
- **World Beer Awards.** Current 2026 country/world/category winners and medal
  tables are machine-readable. Use only an explicit World Best or a uniquely
  ordered relevant winner; medal groups alone are not ranks.
- **MUNDUS VINI.** Blind expert wine competition with Best of Show/category
  distinctions. Exact vintage/DO/bottle identity remains mandatory.
- **Concours Mondial de Bruxelles.** Revelation/top distinctions are useful
  winner sources; ordinary medal sets are not ordered podiums.
- **International Wine Challenge.** Champion and Great Value Champion titles
  are strong; retailer marketplace listings do not prove supermarket stock.
- **Bacchus.** Large blind international wine competition; use explicit
  category-best distinctions, not generic medal lists.
- **World Steak Challenge.** Strong championship source. Lidl España carried
  the 2025 world-winning Irish grass-fed Angus striploin as a limited April
  2026 promotion; retain as a seasonal/promo watch, not current stock.
- **MAPA Alimentos de España** should be treated as a family of national
  winner-only sources (wine styles, spirits, jamón, AOVE and other official
  categories).
- **Producto del Año** and **Sabor del Año** remain discovery-only: the former
  is primarily an innovation award and the latter commonly exposes an unordered
  recognition set. Neither should be promoted to category ranking merely to
  increase content volume.

### Launch matrix after the re-check

Five independent broad categories now satisfy the launch gate:

1. sparkling wine / cava -> NALTROS Brut / ALDI;
2. gazpacho -> Realfooding / Carrefour;
3. AOVE -> Oleoestepa DOP Estepa / Carrefour;
4. coffee capsules -> AROM'ARTE Intenso / DIA;
5. spirits / anís -> Anís Chinchón Dulce / current exact target-chain offer.

At a three-local-day cadence this is approximately fifteen days of initial
runway. Runtime implementation may now begin, but it must use the lean
on-demand ADR rather than the old POC queue/discovery architecture.


## Production Termux retailer HTTP finding — 27 September 2026

The first production-device live preview after merge commit
`e648fbf08c900326d7c61ee877baeac7a24e9652` proved that the award-side
contracts were healthy but the retailer-side request profile was too minimal.

Observed on the actual Termux device:

- OCU cava, OCU gazpacho, OCU AOVE, OCU AROM'ARTE and MAPA spirits authority
  pages all passed their existing source-marker validation.
- ALDI NALTROS passed with the existing exact embedded Next.js contract and
  returned 3.15 EUR.
- Carrefour Realfooding, Carrefour Oleoestepa, DIA AROM'ARTE and Carrefour
  Anís Chinchón all returned HTTP 403 with the service User-Agent.
- Replacing only the retailer request headers with a normal top-level browser
  navigation profile returned HTTP 200 for all four exact product pages.
- The returned HTML stayed small (roughly 70-90 KiB) and contained every
  reviewed exact-product marker; no cookie, JavaScript execution, browser
  runtime, challenge solver, OCR or catalogue crawl was required.

Runtime decision: preserve the lightweight service request profile for award
authorities. Use the proven browser-navigation header profile only for exact
retailer product HTML. Keep the same HTTPS host allowlist, 15-second timeout,
768 KiB ceiling, exact identity markers, product-card price scoping and
fail-closed behaviour.

This is an HTTP compatibility fix, not a relaxation of retail identity or
availability evidence.


A second production-device preview exposed a DIA-specific parser trap after the
HTTP 403 fix: the page header/cart contains `0,00 €` after a repeated document
title, while the actual AROM'ARTE product card contains `3,80 €` immediately
before its `Añadir` button. The original first-title parser therefore selected
the cart total.

Runtime follow-up:
- scope price extraction to the exact-title occurrence nearest the matching
  `Añadir` product-card boundary;
- preserve the existing unavailable/out-of-stock guards so recommendation
  prices cannot leak into the selected product;
- reject zero prices fail-closed, since a zero value is not a publishable
  current supermarket offer for this feature.

The other four live preview prices were correct during the same validation:
NALTROS 3.15 EUR, Realfooding 4.05 EUR, Oleoestepa 7.65 EUR and Anís Chinchón
13.79 EUR.

---

## Autonomous nomination-cycle research — 27 September 2026

### Why the five-item launch pool is not the long-term content model

The production launch gate of five broad categories was intentionally only a
minimum proof that the feature had enough variety to justify implementation.
It is not a statement that only five useful award categories exist.

The durable content unit should be an official, consumer-meaningful nomination,
not merely a broad product category and not merely a medal tier.

A correct hierarchy is:

1. organizer;
2. award programme/competition;
3. consumer product category;
4. semantic nomination;
5. geographic scope when material;
6. source edition;
7. exact winning product;
8. exact current match in one of the six supported supermarkets.

This permits two cheese posts when one is genuinely best goat cheese and the
other best blue cheese, while preventing several near-identical posts merely
because different products received the same Gold/Silver/Super Gold tier.

### Annual publication capacity

One publication at most every three local calendar days yields at most about
122 publication opportunities in a 365-day year.

Treat 122 as a ceiling, not a quota. The bot must stay silent rather than
weaken award semantics, identity or current-retail evidence.

The system does not need 122 ready items at the start of a year. A rolling
buffer of roughly 20-30 publishable nomination events gives 60-90 days of
runway and allows newer annual results to enter naturally during the year.

### Source families and nomination potential

#### OCU

Current official OCU comparators expose 163 comparison tools overall, including
69 in Alimentación:
https://www.ocu.org/todas-las-informaciones/comparadores

This makes OCU the broadest supermarket-oriented source family already found.
Potential food consumer categories include prepared foods, gazpacho, salmorejo,
tortilla, salads, canned tuna, sardines, mussels, frozen fish, milk, yoghurt,
cheese, coffee, capsules, beer, no/low beer, wine/cava, plant drinks, water,
snacks, cereals, biscuits, chocolate, turrón, oils and others.

Useful OCU nomination semantics remain source-native:
- Mejor del Análisis = best result in that comparison;
- Compra Maestra = quality/value distinction;
- Compra ECO = ecological/value distinction.

The main quality stream should prefer Mejor del Análisis. Value/ECO may remain
separate semantic dimensions only if the editorial product explicitly wants them.
Physical-test evidence remains mandatory under the existing OCU guard.

#### MAPA / Alimentos de España

Official recurring family:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos

Wine nominations:
- Mejor Vino Tinto;
- Mejor Vino Blanco;
- Mejor Vino Rosado;
- Mejor Vino Espumoso;
- Mejor Vino de Licor.

2026 winners:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados_vino

Cheese nominations:
- Mejor Queso de Vaca;
- Mejor Queso de Oveja;
- Mejor Queso de Cabra;
- Mejor Queso Mezcla;
- Mejor Queso con Mohos o Queso Azul;
- plus Premio Especial Mejor Queso.

2026 results:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/galardonados_quesos

AOVE nominations:
- Frutado Verde Amargo;
- Frutado Verde Dulce;
- Frutado Maduro;
- Ecológico;
- plus Premio Especial overall.

Recurring campaign page:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/ultima-campana-aceites

Important identity guard: the AOVE competition admits bulk homogeneous lots.
A winning mill/producer cannot be transferred to an arbitrary supermarket
bottle without explicit retail commercial identity.

Jamón nominations:
- Mejor Jamón Serrano u otras Figuras de Calidad Reconocidas;
- Mejor Jamón de Bellota Ibérico.

Recurring page:
https://www.mapa.gob.es/en/alimentacion/temas/promo-alimentos/premios-alimentos/ultima_edicion_jamones

Spirits nomination:
- Mejor Bebida Espirituosa con Indicación Geográfica.

MAPA alone therefore represents many recurring semantic nomination slots, not
one generic MAPA award slot.

#### GourmetQuesos

The reviewed 2026 championship provides 20 cheese categories with explicit
category winners plus an absolute overall winner. It is a strong example of why
consumer-meaningful nomination identity should be retained.

Official 2026 context/results:
https://www.gourmets.net/salon-gourmets/2026/catalogo-expositores/grupo-gourmets/16-gourmetquesos-campeonato-de-los-mejores-quesos-de-espana-2026

The autonomous adapter should allow only reviewed consumer-relevant categories;
it should not create extra events for every lower podium position.

#### International Wine Challenge

Official 2026 trophy page:
https://www.internationalwinechallenge.com/trophy-results-2026.html

High-value semantic nominations include Champion Sparkling, White, Red, Sweet
and Fortified, plus Great Value Champion Sparkling, White, Rosé, Red, Sweet
and Fortified.

National/regional/varietal trophies can create excessive wine volume and should
not be automatically admitted until a consumer-level allowlist is defined.

#### Concours Mondial de Bruxelles

Current Red & White session:
https://concoursmondial.com/en/red-white-wine-session/

Useful explicit nominations include International Red Wine Revelation,
International White Wine Revelation, No-Low Wines Revelation and reviewed
country/session Revelations. Use Revelation titles, not ordinary medal sets.

#### World Beer Awards

Official winner surface has a stable year selector and explicit World's Best
result pages:
https://www.worldbeerawards.com/winner-beer/beer/2026/

Examples include World's Best International Lager, Classic Pilsener, Session
IPA and No & Low Alcohol Speciality. The adapter needs a consumer-level style
allowlist and must not create posts from ordinary medal lists.

#### EVOOLEUM

Official TOP100:
https://www.evooleum.com/evooleum-top100/

Use primarily for the broad global AOVE quality slot and selected reviewed
distinctions, not as a reason to publish dozens of near-identical oils.

### Nomination equivalence and duplicate policy

A minimal semantic key is:
- category;
- subtype/style;
- award dimension;
- scope.

Examples:
- cheese / goat / quality / Spain;
- cheese / blue / quality / Spain;
- wine / sparkling / quality / Spain;
- wine / red / quality / world;
- tuna / olive-oil / laboratory-quality / Spain;
- burrata / consumer-taste / Spain.

Equivalent semantic slots from different organizers should compete by reviewed
source priority instead of producing near-identical posts.

Different dimensions can coexist when they are honestly different: OCU
laboratory/comparative quality and a consumer sensory taste award are not the
same claim.

### Same-product diversity rule

Canonical product identity should preferably be EAN/GTIN; otherwise use an
exact reviewed commercial identity with category-critical variant fields.

Selection should use simple passes rather than a weighted ranking:
1. prefer unpublished events whose product has not appeared in the current
   diversity round and whose category is not in the recent small category window;
2. if none, allow another category even if recently used, still requiring a
   new product identity;
3. only after all currently eligible unique product identities have been used,
   allow the same product again for a different unpublished nomination.

When one product is already known to hold several nominations in the same
source/edition, one stronger article should normally mention the additional
titles rather than spending several three-day slots on that product.

### Annual cycle should be source-driven, not January-1 driven

Do not clear state at New Year. Each source publishes on its own calendar.
Store the latest known edition per source. When a new edition appears:
1. enumerate approved nominations;
2. create new edition-scoped event IDs;
3. supersede the older edition for the same source/nomination;
4. preserve publication history;
5. feed newly matched products into the rolling ready pool.

This permits a smooth 2026 -> 2027 transition without an empty January period
or a destructive reset.

### Retailer-side autonomy: current status

Exact-product verification is already much stronger than autonomous discovery.
The missing piece for multi-year autonomy is a bounded official candidate-search
or index contract for enough of the six chains.

#### Mercadona

Already proven: official exact product IDs, Guardamar warehouse context alc1,
exact product JSON, EAN, supplier, published/availability fields and current
price.

Autonomy gap: prove a browser-free bounded official search/index contract that
can resolve a newly discovered winner to candidate product IDs without a
manually supplied SKU. Exact-name equality remains unsafe because multiple
Mercadona SKUs can share the same visible name.

#### Lidl España

Strong retailer-first discovery surface:
https://www.lidl.es/c/premiados/a10092875

It exposes current awarded food products, often with availability and price.
Use it as a lead generator, then independently verify award semantics.

#### ALDI España

Already strong for exact product validation through embedded first-party
application data and stable identifiers.

Autonomy gap: prove the bounded official search/category contract for resolving
newly discovered winners to ALDI product IDs. Do not build a catalogue crawler.

#### Consum

Current exact pages are strong: stable Código producto, often EAN, package and
current price.

Autonomy gap: prove the official bounded search/index path that returns
candidate product IDs/EAN for an award winner.

#### Carrefour España supermarket

Current server-rendered supermarket pages expose exact name, package, price and
detailed product identity.

Permanent guards: supermarket surface only; reject third-party marketplace;
include package/variant; retain the proven browser-navigation request profile.

Autonomy gap: prove a bounded first-party supermarket search/result contract.

#### DIA España

Strong current award/category pages with stable SKU IDs:
https://www.dia.es/l/productos-premiados-dia
https://www.dia.es/novedades-y-recomendados/productos-premiados/c/L2329

They expose names, numeric SKUs, prices and Add/Agotado state and are useful
retailer-first leads. Independent award semantics remain preferable.

### Retail match algorithm without overengineering

For one official award winner:
1. use exact EAN from the award authority when available;
2. otherwise query each proven official retailer search adapter with exact
   commercial name/brand;
3. inspect only a small top-N result set;
4. open the exact first-party candidate page;
5. require EAN/SKU or exact category-specific identity;
6. stop after the first sufficiently strong supported-retailer proof;
7. store only the stable retailer identity;
8. refresh availability and price immediately before publication.

There is no requirement to find every chain carrying the product. One exact
current supported-retailer match is enough.

### Why one generic supermarket crawler is rejected

The six chains expose different contracts: Mercadona JSON/API identity, Lidl
award/category pages, ALDI embedded application data, Consum product code/EAN
pages, Carrefour supermarket HTML plus marketplace guard, and DIA SKU/category
HTML.

A generic crawler would need fuzzy matching and retailer-specific exceptions
anyway. Six small adapters are simpler and safer.

### Rolling discovery without another resident service

Keep one one-shot runtime model. A future autonomous implementation can use
the existing scheduled invocation with state gates:
- normal day with healthy buffer: state-only / publication logic;
- source check due or pool below low-water mark: bounded discovery/refill;
- publication due: exact offer refresh and at most one Telegram send.

No resident worker, browser or database is required.

### Recommended ready-buffer policy

Do not attempt to prove 122 retail matches at once.
Suggested policy:
- target buffer: 20-30 ready nomination events;
- low-water mark: about 15;
- refill in small bounded batches;
- price is not frozen during refill;
- unavailable candidates remain retryable or are superseded by newer editions;
- retire an older equivalent edition when a newer edition is available.

### Autonomy boundary

A multi-year autonomous cycle is realistic while reviewed external contracts
remain valid: new editions are detected, nominations enumerated, products
matched through official retailer adapters, the pool replenished and publication
scheduled automatically.

It is not realistic to promise zero maintenance for arbitrary third-party HTML
over several years. Contract drift in one source should isolate that source,
continue with healthy sources and emit an actionable diagnostic.

### Implementation research gates before code

Do not implement the autonomous cycle yet.

First prove read-only:
1. at least four recurring award sources can enumerate latest-edition
   nomination winners with bounded anonymous HTTP;
2. official candidate-search/index contracts for the target retailers, or
   enough of them to generate a useful pool;
3. candidate search yields exact EAN/SKU joins rather than fuzzy-name joins;
4. a 2026 dry run produces substantially more than the five launch events;
5. the diversity selector fills a realistic sequence without adjacent duplicate
   products/categories;
6. source and retailer request budgets remain compatible with the Termux phone.

ADR 0085 records the proposed architecture. ADR 0083 remains the active
production architecture until these gates pass.

### Second architecture review: health, article richness and media

#### Admin observability without a monitoring subsystem

The autonomous design needs one private administrator alert path, but not a new
monitoring service. Adapter health can live in the same compact product-award
state and alerts can be emitted by the existing one-shot execution when health
changes.

Important distinction:
- no product match, sold-out product, below-threshold quality or no new edition
  are normal content outcomes and must not page the administrator;
- parser/schema drift, contract-breaking 403/404, invalid response contract,
  persistent transport failure or ambiguous result structure are operational
  failures and should mark that component degraded/broken.

Alert only on transitions. Deterministic schema/contract failures alert once
immediately; transient network failures require a small repetition/sustained
failure threshold. The same fault remains silent until recovery, and recovery
sends one confirmation.

Every alert should identify the feature and stage, for example:
`Product Awards / award source / MAPA cheese / RESULT-SCHEMA` or
`Product Awards / retailer search / Carrefour / HTTP-403`.

Safe alert context should include diagnostic code, first/last failure time,
impact and remaining ready-pool runway, but never credentials or arbitrary
source response bodies.

A separate runway transition warning is valuable even when no adapter is
technically broken. Crossing below a small ready-pool threshold can warn the
administrator weeks before content is exhausted.

#### OCU is a rolling source, not strictly an annual source

OCU's own comparator documentation states that some comparators update every
15-30 days while others update one or more times per year:
https://www.ocu.org/consumo-familia/derechos-consumidor/informe/comparadores

Therefore the generic autonomous identity must use a source cycle/revision, not
assume that every event is keyed only by year. Annual award bodies can simply
use their edition year as the source cycle.

#### Rich article evidence is available without runtime AI

Several authoritative sources publish enough methodology to create much richer
deterministic articles.

OCU currently documents that selected products are purchased anonymously like a
normal consumer and sent to independent specialist laboratories. Its award
labels remain Mejor del Análisis, Compra Maestra and Compra ECO:
https://www.ocu.org/info/quienes-somos/nuestros-analisis

MAPA's 2026 cheese award publishes unusually rich process facts: admitted
producer/sample requirements, sensory score sheets, panels of five expert
tasters, a two-stage selection, an 80-point threshold for finalists and
physical-chemical/microbiological/species checks:
https://www.mapa.gob.es/es/alimentacion/temas/promo-alimentos/premios-alimentos/ultimaedicionpremioquesos

International Wine Challenge publishes a blind multi-stage judging process.
Wines are grouped into coded tasting flights; initial panels contain 3-4 expert
judges from roles such as winemakers, buyers, sommeliers and educators, and
medal wines are re-tasted/confirmed at senior level:
https://www.internationalwinechallenge.com/judging-process.html

GourmetQuesos 2026 publishes more than 800 entries, 65 judges, two qualifying
phases, 20 categories, finalists and sensory criteria including rind, colour,
texture, aroma, flavour, aftertaste and persistence:
https://www.gourmets.net/salon-gourmets/2026/catalogo-expositores/grupo-gourmets/16-gourmetquesos-campeonato-de-los-mejores-quesos-de-espana-2026

World Beer Awards documents a three-round taste hierarchy: country style
winners, worldwide style comparison, then World's Best category titles. Its
official material describes specialist/international beer-expert panels and
blind judging:
https://www.worldbeerawards.com/how-to-enter

These examples support a deterministic rich-article model with fields such as
entry/sample count, judge/tester count, blind/lab flags, judging phases,
criteria, score, producer, origin and category-specific product attributes.

Each fact must retain source provenance. Award methodology comes from the award
authority; current price/availability/package comes from the retailer.

#### Image transport is easy; reuse rights are the real gate

Telegram Bot API `sendPhoto` accepts an HTTP URL and Telegram downloads the
remote image. Current Bot API documentation also limits photo captions to 1024
characters and states a 5 MB limit for photos sent by URL:
https://core.telegram.org/bots/api

The repository already contains a bounded HTTPS `send_photo_url` implementation,
so image transport does not require a new dependency.

However, the retained legal review already found restrictive reproduction/public
communication terms for several retailer sites. A public product-image URL is
therefore not enough to permit republication in Telegram.

Preferred image evidence order:
1. award organizer press/media asset with explicit reuse permission;
2. producer/manufacturer press asset with explicit reuse permission;
3. retailer product image only where reuse permission is clear;
4. otherwise text-only.

To avoid two-message transactional complexity, first keep one publication as
one Telegram message: use photo+caption only when the approved image exists and
the complete article fits the 1024-character caption; otherwise publish the
richer text-only article.

#### Overengineering review

Still rejected:
- universal award scraper;
- generic supermarket crawler;
- search-engine runtime discovery;
- browser/Playwright/Selenium;
- OCR for normal award/runtime paths;
- LLM extraction, translation or product matching;
- fuzzy similarity identity joins;
- relational database/vector index;
- separate daemon per source or retailer;
- continuous stock/price monitoring;
- automatic two-message photo/article bundle in the first autonomous version.

Still justified:
- one small adapter per recurring award source;
- one small search/identity adapter per supported retailer where a cheap
  official contract is proven;
- one compact rolling ready pool;
- one controlled semantic nomination vocabulary;
- one small health map with transition-based admin alerts;
- deterministic source-specific rendering;
- one exact offer refresh immediately before publication.

#### Remaining research before implementation

1. Prove bounded browser-free search/index contracts for the six target
   retailers, prioritising Mercadona, ALDI, Consum and Carrefour because their
   exact-product refresh is already stronger than discovery.
2. Run a real 30-50 winner dry sample across OCU/MAPA/IWC/GourmetQuesos and
   measure exact retail-match yield in the six chains.
3. Record request counts, payload sizes, false/ambiguous matches and the number
   of candidates that resolve by EAN, retailer SKU or exact commercial identity.
4. Estimate actual ready-event runway after semantic deduplication and physical
   product diversity rules.
5. Test source health-state transitions and admin-alert wording without sending
   public messages.
6. Audit image reuse rights source-by-source; do not make product photos a
   launch gate for autonomy.

Only after this dry research demonstrates a sufficiently large and cheap pool
should ADR 0085 move from Proposed toward Accepted.


### Full retailer search/index research — 27 September 2026

#### Research question

Can the autonomous nomination-cycle architecture resolve a newly discovered
award winner into one exact current product in the six supported supermarket
chains without a browser, OCR, runtime AI, fuzzy matching or a full catalogue
crawl?

The investigation used three evidence layers:

1. official retailer/result surfaces and current robots/search behaviour;
2. existing first-party exact-product contracts already proven in this project;
3. a current independent browser-free supermarket client implementation
   (jgalea/grocery-cli) as corroborating evidence for storefront search/index
   contracts, never as award or retail truth.

The independent client is useful because it implements current 2026 browser-free
search against the same retailer storefront backends for Mercadona, ALDI,
Consum, DIA and Lidl España. Its fuzzy multi-store comparison logic is not
suitable for this project and must not be reused. Only raw candidate-search
contracts and ids are relevant.

#### Retailer capability matrix

| Retailer | Search/index contract | Exact identity/refresh | Architecture result |
| --- | --- | --- | --- |
| Mercadona | storefront Algolia search, warehouse-specific index | first-party product JSON with id/EAN/price/supplier | GREEN with rotating-config risk |
| ALDI España | storefront Algolia, peninsula/Canarias/Baleares indexes | exact first-party product/embedded app data | GREEN |
| Consum | first-party REST catalog search | first-party REST detail, stable product code and often EAN | GREEN / strongest clean contract |
| DIA España | first-party search/category JSON | exact SSR product with stable SKU | AMBER-GREEN; prefer retailer-first/limited search |
| Lidl España | first-party /q/api/search JSON | exact first-party product page | AMBER-GREEN; positive-only, incomplete grocery assortment |
| Carrefour España supermarket | human search exists but generic browser-free automation is bot-managed/restricted | exact supermarket product card works | AMBER; validation-only in v1 |

No architecture benefit justifies adding a browser solely to make Carrefour
generic search work.

#### Mercadona search/index

Existing project research had already proven Guardamar exact-product context:

- postal code 03140 resolves to warehouse alc1;
- exact first-party endpoint pattern:
  https://tienda.mercadona.es/api/products/<id>/?lang=es&wh=alc1
- exact product data can expose product id, EAN, display name, brand/supplier,
  price and current publication/availability facts.

Current independent storefront implementation confirms that search runs through
Mercadona's web-app Algolia index using public search-only configuration shipped
to the browser:

- index pattern: products_prod_<warehouse>_<lang>;
- POST one query with a bounded hitsPerPage;
- returned candidates include numeric id, display name, slug/share URL and
  current price data;
- exact candidate detail is then read from Mercadona's first-party REST product
  endpoint.

Important durability caveat: the public Algolia application/key are storefront
configuration and can rotate. They must not be hard-coded as durable secrets.
A future adapter needs a small reviewed mechanism to obtain/refresh the current
public search configuration and an admin health alert if that contract drifts.

Important identity caveat: earlier project research proved that two Mercadona
SKUs can share the same visible product name. Search therefore generates
candidates only; exact detail/EAN/variant proof remains mandatory.

Result: browser-free autonomous candidate search is technically realistic and
high-value for Mercadona, with a moderate maintenance risk concentrated in the
public search configuration.

#### ALDI España search/index

ALDI España's current storefront is backed by public search-only Algolia indexes.

The reviewed current contract uses regional indexes:

- peninsula: the relevant region for Guardamar;
- Canarias;
- Baleares.

Search returns candidate records with:

- object id / article identity;
- name;
- brand;
- product slug;
- sales unit;
- current price/base price;
- availability;
- categories.

The current storefront search behaviour also relaxes trailing query words when a
strict query has no result. This matters because ALDI stores package size
separately from product name; blindly searching an award string containing
"750 ml" can otherwise create a false no-match.

Existing production research already proved exact first-party ALDI detail for
NALTROS through embedded application data, including article number, brand,
sales unit, availability and current price.

Result: ALDI is suitable for bounded browser-free search + exact validation.
Keep the search index/configuration source-specific and health-monitored; do not
generalise into a catalogue crawler.

#### Consum search/index

Consum currently exposes the cleanest direct first-party browser-free contract
in the target set.

Search pattern:

https://tienda.consum.es/api/rest/V1.0/catalog/product?q=<term>

Exact product pattern:

https://tienda.consum.es/api/rest/V1.0/catalog/product/<product-id>

Current product structures expose:

- stable numeric product id / Código producto;
- product name;
- EAN on exact detail when present;
- current price;
- unit price/unit type.

This is unusually well aligned with the autonomous identity gate because a
search candidate can be promoted to exact EAN proof without scraping a rendered
page.

A current dry-run also found a strong GourmetQuesos candidate in Consum:
Los Cameros Semicurado Mezcla, product code 7480085. The brand + semicurado +
mezcla identity is much stronger than a family-name match, but this research
still treats it as CANDIDATE until exact detail/EAN/maker proves the winning
commercial product beyond doubt.

Result: Consum should be one of the first autonomous retail adapters.

#### DIA España search/index

A current browser-free implementation confirms first-party search/category
microservices on dia.es:

Search:
https://www.dia.es/api/v1/search-back/search?q=<term>

Category listing:
https://www.dia.es/api/v1/plp-back/products?navigation=<category>

Search results can expose:

- stable object/SKU id;
- display name;
- brand;
- exact product URL;
- current price and unit price.

Exact product detail remains the server-rendered product page; production has
already proven that DIA exact pages work with the reviewed navigation-header
profile and strict product-card price scoping.

However, current DIA robots rules explicitly restrict several search/query
surfaces and ask to reduce Algolia hits. Therefore the architecture should not
turn this into a broad daily generic search service.

Preferred use:

1. retailer-first DIA award/category pages when available;
2. exact SKU from those pages;
3. bounded generic search only after a deliberate policy/contract review.

DIA's official awarded-products surface is particularly valuable because it
already gives exact current retail products for Sabor del Año 2026 such as the
DIA Selección Mundial burrata and Caprichoso cheesecake.

Result: technically capable, but use retailer-first and narrowly bounded search
rather than aggressive generic search.

#### Lidl España search/index

Lidl España exposes a first-party browser-free JSON search endpoint under:

/q/api/search

The reviewed query contract requires:

- q=<term>;
- assortment=ES;
- locale=es_ES;
- version=2.0.

The response can expose:

- item/code/ERP identifiers;
- full title;
- category;
- brand;
- canonical URL;
- current price/base price.

The edge behaviour is unusual: the reviewed implementation uses Accept: */*
because a JSON-specific Accept header can produce HTTP 406.

Important limitation: Lidl's online search surface reflects current online/
weekly assortment and is not a complete grocery catalogue. Therefore:

**positive Lidl search hit is useful evidence; Lidl search miss is never proof
that a product is absent from Spanish stores.**

Lidl's official Productos Premiados page is more valuable than generic search
for this feature because it already supplies a bounded set of currently awarded
products across cheeses, meat, fish, wine and other food. Those are retailer
leads only: independent award-authority semantics still need verification.

Result: Lidl is a strong retailer-first/positive-only adapter, not an absence
oracle.

#### Carrefour España supermarket search/index

Carrefour is the only target retailer for which the research does not support a
lean generic autonomous search adapter today.

Positive evidence:

- Carrefour's own FAQ explains that the site lets customers search by product
  name or EAN;
- exact supermarket product cards expose useful current name/package/price
  evidence;
- production already proved exact Carrefour product pages can be fetched
  browser-free with the reviewed navigation request profile.

Negative architectural evidence:

- current robots rules restrict /buscador/, ajax search and query/filter
  patterns;
- current independent plain-HTTP supermarket tooling deliberately excludes
  Carrefour because its bot-management layer is not reliably cleared without a
  browser/stealth approach;
- Carrefour Marketplace creates a permanent false-positive trap: a third-party
  marketplace listing is not evidence of a Carrefour supermarket shelf item.

Result: **Carrefour should be validation-only in autonomous v1.**

If an award source, retailer-first source, exact EAN or another reviewed path
already yields a Carrefour supermarket product URL, use the existing exact-card
refresh. Do not add Playwright, proxy rotation, CAPTCHA solving or a stealth
browser merely to obtain generic search.

#### Search-miss semantics

A critical architecture correction follows from the retailer study.

Retail search is primarily a **positive-evidence generator**.

A search hit can create an exact candidate. A miss must normally mean only:

NO_VERIFIED_MATCH

not:

PRODUCT_NOT_SOLD

This rule prevents a dangerous interaction with ranked award fallbacks.

Example: if OCU says #1 is a specific ALDI private-label tuna and our search
adapter fails to find its exact olive-oil SKU, that miss is not enough to
publish OCU #2 from Mercadona. The #1 product may still exist under a search
shape our adapter missed.

A lower rank may replace #1 only after stronger evidence establishes that #1
does not qualify in current target retail scope, or when a reviewed
source-specific rule safely establishes fallback eligibility.

This is stricter but avoids silent ranking corruption.

#### Pre-search identity gate

The dry-run showed that a cheap identity filter should happen before any store
queries.

Do not search retailers when the award source supplies only:

- producer/mill identity without a tied commercial SKU;
- a bulk lot;
- generic product family;
- incomplete wine identity missing required vintage/cuvée/DO;
- foreign supermarket private label outside the six target chains.

Concrete example: MAPA AOVE competition awards homogeneous bulk lots and
producer/mill results. Without an explicit commercial retail bottle identity,
retailer search would invite unsafe award transfer and should be skipped
entirely.

Likewise, an IWC winner that is explicitly a Tesco/Sainsbury/Asda private label
can be rejected before querying any Spanish chain.

This gate reduces both false matches and request volume.

#### Practical 49-event dry sample

A stratified dry sample was assembled from current real award events rather than
retailer-friendly handpicked products.

Sample composition:

- 20 GourmetQuesos 2026 category winners;
- 5 MAPA 2026 cheese modality winners;
- 5 MAPA 2026 wine modality winners;
- 2 MAPA jamón winners;
- 1 MAPA spirits winner;
- 8 IWC champion/great-value candidates with potentially transferable
  commercial identity;
- 8 OCU supermarket-oriented products/results.

Strict results under the original six-retailer scope:

- 5/49 were publishable at the time of the first dry-run:
  NALTROS Brut, Realfooding Gazpacho, Oleoestepa DOP Estepa,
  AROM'ARTE Intenso and Anís Chinchón Dulce;

After the local-scope amendment that removes Carrefour, only 3/49 remain
directly proven in-scope today: NALTROS Brut, AROM'ARTE Intenso and Anís
Chinchón Dulce. Realfooding Gazpacho and Oleoestepa DOP Estepa become
UNRESOLVED until another active retailer (especially Masymas) is proven.
- one additional exact current retail product (Hacendado tuna) is known but is
  not publication-eligible while the higher-ranked Sal de Plata/ALDI winner
  remains unresolved;
- El Almendro Turrón Duro has a current exact Carrefour product identity but the
  reviewed card is temporarily unavailable/sold out;
- Los Cameros Semicurado Mezcla produced a strong current Consum candidate that
  still requires final exact-detail/EAN proof;
- the remaining sampled specialist/global winners did not produce exact current
  first-party retail proof under the strict match rules.

The original aggregate publishable yield was about 10%. Under the revised
local retailer scope the currently proven yield is about 6% before Masymas
search is tested. Neither percentage is a forecast for the autonomous feed:
the sample intentionally over-represents low-yield specialty/global
competitions, and Masymas has not yet contributed any search results.

The stratified signal is more important:

| Source family | Sample | Strict current signal |
| --- | ---: | --- |
| OCU supermarket-oriented | 8 | 2 directly proven in revised scope today; 2 former Carrefour-backed matches now UNRESOLVED; additional exact/block/sold-out cases exist |
| MAPA non-AOVE product winners | 13 | 1 exact publishable current winner |
| GourmetQuesos | 20 | 0 confirmed READY; 1 strong Consum candidate |
| IWC selected champions/value winners | 8 | 0 exact current target-chain matches established |

The architecture implication is clear: do not give all source families equal
refill priority.

#### False positives observed during dry-run

The strict matcher correctly needs to reject cases such as:

- Carrefour currently carries Caprillice-branded products, but the observed
  variants are not the GourmetQuesos-winning Semicurado al vino Caprillice;
- Cremositos del Zújar appears in a Carrefour Marketplace third-party basket,
  which is not Carrefour supermarket shelf evidence;
- Savel can appear in Carrefour editorial/event context without being a
  supermarket product;
- producer/brand family equality without the exact winning variant.

These are realistic failures that a fuzzy or AI matcher would be tempted to
promote incorrectly.

#### Source-yield-aware refill without a ranking engine

The dry-run justifies one simple static source order.

High-yield first:
- OCU and other supermarket comparative sources;
- Lidl/DIA retailer-award lead surfaces, followed by independent authority
  verification.

Then:
- MAPA and Spanish specialist sources.

Then:
- global competitions such as IWC/CMB/World Beer Awards when the ready pool
  still needs diversity.

This is not a quality ranking of the award bodies. It is a phone-cost and
supermarket-match optimisation.

Global competitions remain editorially valuable; they simply have a lower
probability that the exact winner is stocked in the six local chains.

#### Sabor del Año: high potential, wrong award-first surface

Sabor del Año is strategically interesting because its method is consumer
sensory testing and 2026 reporting covers many retail products.

The reviewed methodology uses 80 habitual consumers of the category, blind
individual tasting and criteria including taste, appearance, smell, texture and
overall satisfaction. A winner must exceed 6/10 and have the highest category
score.

However, the current official 2026 winner catalogue is largely image-based and
does not expose a clean text/result index suitable for this project's no-OCR
runtime.

Do **not** add OCR merely to unlock this source.

Instead use retailer-first current award pages such as DIA and Lidl to generate
exact current product leads, then verify the Sabor del Año award semantics
through whatever official structured evidence is available for that specific
product/category. If that exact authority join cannot be proven cheaply, keep
the lead out of autonomous READY state.

#### Recommended autonomous retail architecture after search research

The minimum useful v1 is now narrower than the earlier six-search-adapter idea:

- Mercadona: search + exact verify;
- ALDI: search + exact verify;
- Consum: search + exact verify;
- DIA: retailer-first + optional bounded search + exact verify;
- Lidl: retailer-first + positive-only search + exact verify;
- Carrefour: exact verify only.

This already covers all six public retail destinations without introducing a
browser.

A nomination event may carry retailer hints from the award source or retailer
lead. The engine checks hinted retailers first and stops after one exact current
supported-retailer match.

No price comparison across stores is necessary.

#### Remaining evidence before runtime implementation

The web/source research is now sufficient to choose the potential architecture,
but implementation should still wait for one final read-only device-level
contract probe.

That probe should verify from the actual Termux production network:

- Mercadona Algolia search against alc1 and exact product detail;
- ALDI peninsula Algolia search and exact product detail;
- Consum REST search and exact detail/EAN;
- DIA narrowly bounded search/category call and exact product SSR;
- Lidl /q/api/search with the exact required headers/parameters and one exact
  page;
- Carrefour remains exact-card-only.

The probe should record only status code, content type, response bytes, result
count and a few safe identity fields. It must not create state, write crontab or
send Telegram messages.

If those device probes reproduce the researched contracts, the retailer side of
ADR 0085 is strong enough for a prototype autonomous dry-run.



### Local retailer-scope amendment: remove Carrefour, add Masymas — 27 September 2026

#### Final active retailer set for the autonomous research

Carrefour is removed completely from the future autonomous Product Awards
retailer scope. This is both a simplification and a local-utility correction:
there is no Carrefour supermarket in Guardamar, while Masymas / Juan Fornés
does have a Guardamar store.

The target six are now:

1. Mercadona;
2. Masymas / Juan Fornés Fornés;
3. ALDI España;
4. Lidl España;
5. DIA España;
6. Consum.

Earlier Carrefour search/validation findings remain historical evidence only and
must not be carried into ADR 0085 implementation.

#### Masymas / Juan Fornés identity and local relevance

The target Masymas is **Juan Fornés Fornés, S.A.**, the Valencian/Murcian chain,
not another retailer using a similar masymas name.

Official company/current ecommerce evidence:

- Masymas terms identify JUAN FORNÉS FORNÉS, S.A. as the online seller.
- Official online-purchase terms state that product prices are the current
  prices shown on the Masymas website and that orders are subject to current
  stock/availability.
- The delivery scope includes towns in which there is a Masymas Fornés store.
- Guardamar del Segura has a Masymas supermarket at Av. del Puerto 18-20.
- The online store has been publicly described by Juan Fornés as offering about
  8,000 references.

Official/storefront sources:

- https://masymas.com/es/condiciones-de-compra-online
- https://tienda.masymas.com/
- https://www.masymas.com/es/empresa/historia-fornes.html

#### Masymas platform/search hypothesis

The official Masymas online storefront is a JavaScript application that loads
assets from the Fornés-specific Aktios domain:

`cdn-fornes.aktiosdigitalservices.com`.

Aktios' own eCommerce page lists both **Consum** and **Masymas** among the
supermarket chains using its eCommerce platform. Consum's current TOL-style
catalogue REST contract is already proven in this research.

This is strong evidence that Masymas may expose a similar first-party catalogue
API family, but it is **not enough to copy Consum endpoints by assumption**.

Masymas therefore remains:

- platform identity: PROVEN;
- official online catalogue/current prices: PROVEN;
- local Guardamar relevance: PROVEN;
- exact browser-free search endpoint: PENDING production-device probe;
- exact product/EAN endpoint: PENDING production-device probe.

The first production-device probe should test the same TOL namespace only as a
hypothesis and, if needed, inspect a bounded number of first-party frontend
bundles for literal API path strings. No browser is required for that probe.

If Masymas exposes a stable TOL search/detail contract, it becomes one of the
strongest retailers in the architecture because it is both locally present and
built for online grocery ordering.

If it does not, leave Masymas retailer-first/category-page or validation-only;
do not introduce browser automation merely to force search.

#### Multiple SKUs can be useful package options

The earlier Mercadona warning that one visible product name can map to multiple
SKUs should not be interpreted as "choose exactly one SKU".

Real current evidence shows the useful case:

- Mercadona SKU 39901: Hacendado fresh salmorejo, 1 L;
- Mercadona SKU 39966: Hacendado fresh salmorejo, 0.33 L.

The visible commercial name is the same and the variants are useful consumer
package options. OCU's 2026 salmorejo methodology, however, explicitly says the
comparison bought **1-litre salmorejos**, so the tested award evidence is tied
at least to a 1 L sample.

This leads to a stricter but more useful rule:

1. one SKU is the **award-anchor offer** when its package/variant matches the
   tested or awarded identity exactly;
2. additional SKUs may be shown as **equivalent package options** only when
   first-party evidence proves that they are the same commercial formulation
   and differ only by package/quantity;
3. alternative packaging never changes the award event identity;
4. different recipes/flavours/vintages/maturation/origin/quality tiers remain
   different products even if the visible name is similar.

The optional additional offers should not block publication. One exact award
anchor is sufficient.

This avoids both extremes:
- throwing away useful small/large package prices;
- incorrectly transferring an award to a merely similar SKU.

#### Diversity identity with package variants

All proven package variants of the same awarded commercial product share one
canonical product key for scheduling.

Therefore:
- 0.33 L and 1 L Hacendado salmorejo do not count as two different products;
- they may appear together in one article;
- they do not consume separate diversity slots;
- a later genuinely different nomination for the same canonical product is
  considered a repeat product under the existing diversity-round rules.

#### Current launch baseline after Carrefour removal

The historical five READY production items cannot be reused unchanged for the
future autonomous scope.

Still directly supported inside the new six-retailer scope:

- NALTROS Brut -> ALDI;
- AROM'ARTE Intenso -> DIA;
- Anís Chinchón Dulce -> DIA and Consum.

No exact current first-party match has yet been established in the new scope
for:

- Realfooding Gazpacho, previously validated through Carrefour;
- Oleoestepa DOP Estepa, previously validated through Carrefour.

Those two become **UNRESOLVED under the new retailer scope**, not automatically
invalid. Masymas search is one of the first useful places to test them once its
production-device search contract is proven.

The historical Product Awards runtime currently deployed is intentionally not
changed by this research PR. This amendment describes only the prospective ADR
0085 autonomous architecture.

#### New search priority after local-scope change

When an award source provides no retailer hint, use local utility plus contract
quality to avoid needless requests.

Suggested initial order:

1. Mercadona — local Guardamar store, strong search/detail identity;
2. Masymas / Juan Fornés — local Guardamar store, once TOL contract is proven;
3. Consum — very strong product-code/EAN contract;
4. ALDI — strong peninsula search;
5. DIA — retailer-first/limited search;
6. Lidl — retailer-first/positive-only search.

A source-provided explicit retailer hint overrides this order. Example: an OCU
winner labelled ALDI goes directly to ALDI first.

The engine still stops after one exact eligible retailer is found, while that
retailer's same-product package variants may be collected cheaply for optional
price display.

#### Revised retailer contract table

| Retailer | Candidate search | Exact identity | Local/runtime role |
| --- | --- | --- | --- |
| Mercadona | proven storefront Algolia | proven product JSON / SKU / EAN | GREEN, local-first |
| Masymas / Juan Fornés | TOL-style contract strongly indicated, exact endpoint pending phone probe | official online catalogue/pricing proven; API detail pending | AMBER, high-priority local target |
| Consum | proven first-party REST search | proven product id + often EAN | GREEN |
| ALDI España | proven regional Algolia | proven exact product/application data | GREEN |
| DIA España | technically proven search/category JSON | proven stable SKU + exact SSR | AMBER-GREEN, prefer retailer-first |
| Lidl España | proven JSON search, incomplete online grocery coverage | exact first-party page | AMBER-GREEN, positive-only |

Carrefour is no longer part of the table.

#### Revised production-device probe gate

Before ADR 0085 is accepted, the actual Redmi/Termux network must perform one
read-only bounded probe for:

- Mercadona: search against the Guardamar `alc1` index plus exact product;
- Masymas: storefront HTML/platform markers, candidate TOL catalogue/search
  endpoint, exact detail/EAN if exposed;
- Consum: REST search plus exact detail/EAN;
- ALDI: peninsula search plus exact product;
- DIA: one bounded search/category request plus exact SSR product;
- Lidl: `/q/api/search` with required parameters/headers plus one exact page.

The probe records only safe operational facts: HTTP status, content type,
bounded byte count, number of results and a few identity fields.

It creates no state, changes no cron and sends no Telegram message.


### Production-device retailer contract proof — 27 September 2026

The final read-only retailer probe was executed on the actual Redmi/Termux
production device at repository HEAD
`6fb2bcdd6f29049f0c39e7d8ca5123482749276e`.

Safety checks proved that the probe had no side effects:

- repository HEAD before/after: unchanged;
- `state/product_awards.json`: absent before and after;
- crontab SHA-256 before/after:
  `9aa0e04ae54495fe8c678f8821dc3741f5581a4cc7804fc015ac8e06e35462b2`;
- no Telegram call;
- no cron write;
- no product-award state write.

#### Mercadona production proof

Warehouse-specific search index:

`products_prod_alc1_es`

returned:

- HTTP 200;
- `application/json`;
- 19,112 bytes;
- 8 bounded hits for `salmorejo hacendado`.

Observed candidates included:

- SKU 39901 — `Salmorejo fresco Hacendado` — 2.90 EUR;
- SKU 39966 — `Salmorejo fresco Hacendado` — 1.25 EUR;
- SKU 39902 — `Salmorejo al estilo cordobés Hacendado` — 2.20 EUR;
- SKU 39903 — `Salmorejo al estilo cordobés Hacendado` — 2.65 EUR;
- additional gazpacho variants.

Exact `alc1` product JSON also returned HTTP 200.

Identity examples:

- 39901 -> EAN 8480000399014;
- 39966 -> EAN 8480000399663;
- 39902 -> EAN 8480000399021;
- 39903 -> EAN 8480000399038.

All four exact records were currently published and exposed current price plus
reference price/unit.

This is direct production proof that Mercadona candidate search and exact
EAN-level verification both work without a browser.

It also proves why the model must distinguish canonical product from retail
offer SKU: two current SKUs share the visible name `Salmorejo fresco
Hacendado` but have different EANs and package economics.

The probe alone does **not** prove that those two SKUs have identical
formulation. Package-equivalence enrichment still requires first-party
composition/variant evidence.

#### Masymas / Juan Fornés production proof

Official storefront:

- HTTP 200;
- 23,361 bytes;
- Fornés CDN marker present;
- Aktios marker present;
- TOL marker present.

The exact hypothesised first-party endpoint worked immediately on the phone:

`https://tienda.masymas.com/api/rest/V1.0/catalog/product?q=<term>`

A broad `leche` query returned:

- HTTP 200;
- JSON;
- 71,817 bytes;
- 20 products.

Candidate records exposed numeric product id, EAN and product name.

Examples:

- id 2034 / EAN 8411700011302 / `Bebida Láctea Omega3 Con Nueces`;
- id 1843 / EAN 8411700010121;
- id 1691 / EAN 8411700412321.

This converts Masymas from a platform hypothesis into a proven browser-free
first-party search contract on the actual production network.

Additional award-related probes:

**realfooding**
- HTTP 200;
- 1 result;
- product id 9079 / EAN 8424465845242;
- product name `Pan 100% Integral`.

This is not the awarded Realfooding gazpacho and therefore is rejected.

**oleoestepa**
- HTTP 200;
- zero products.

This is `NO VERIFIED MATCH`, not proof that Oleoestepa is absent from all
Masymas stores.

**chinchon**
- HTTP 200;
- 15 results;
- examples were `Queso Fresco Cincho...`, `Salchichón...` and other
  substring/lexical matches.

This is a valuable negative test: Masymas search is not an exact identity
matcher. EAN/exact commercial identity filtering is mandatory after candidate
retrieval.

Masymas is now **GREEN for candidate search**. Search already exposes EAN.
However, publication-time exact current price/availability still needs one small
device proof tying a returned product id/EAN to a first-party exact-offer surface.

#### ALDI production proof

Peninsula index:

`an_prd_es_es_pen_products2`

Search `naltros` returned:

- HTTP 200;
- 6,072-byte JSON;
- 3 exact brand variants.

Observed current variants:

- article/object 191000 — NALTROS cava brut nature — 0.75 L — available —
  3.79 EUR;
- 190300 — NALTROS cava brut — 0.75 L — available — 3.15 EUR;
- 190000 — NALTROS cava semiseco — 0.75 L — available — 2.99 EUR.

The exact NALTROS page returned HTTP 200, 71,538 bytes and retained expected
brand/article/Next.js application markers.

This is strong production proof for browser-free candidate search plus exact
verification.

#### Consum production proof

Search for `chinchon` returned:

- HTTP 200;
- 1,886-byte JSON;
- 1 product.

Current candidate:

- product id 19967;
- EAN 8410023172240;
- `Anís Dulce Botella`.

Exact product detail for id 19967 returned:

- HTTP 200;
- 1,819-byte JSON;
- the same EAN and product name.

Consum therefore has the cleanest fully proven search -> id -> exact EAN
pipeline in the active retailer set.

#### DIA production proof

Generic search:

`/api/v1/search-back/search?q=arom%20arte%20intenso`

returned:

- HTTP 403;
- HTML error response;
- 410 bytes.

Exact AROM'ARTE page returned:

- HTTP 200;
- 70,475 bytes;
- correct product/SKU/add-to-cart markers.

Therefore DIA generic search must be **excluded** from the production autonomous
architecture.

DIA remains useful through:

- official awarded-product/category pages;
- exact numeric SKU links obtained from those pages;
- exact SSR product refresh before publication.

This is simpler than trying to emulate or bypass DIA search protection.

#### Lidl production proof

Official search:

`/q/api/search?q=queso&assortment=ES&locale=es_ES&version=2.0`

returned:

- HTTP 200;
- content type `application/mindshift.search+json;version=2`;
- 447,279 bytes;
- 35 current results.

Observed fields included item/code/ERP id, brand, full title, current price when
present and canonical product URL.

Examples included current ITALIAMO Parmigiano Reggiano D.O.P., MILBONA processed
cheese, sheep cheese and Roncero products.

The exact first returned product page also returned HTTP 200 and valid HTML.

The 447 KiB response confirms that broad Lidl category-style queries are too
expensive for normal refill. Runtime Lidl discovery must use exact award/product
terms or retailer-first awarded-product pages and retain a strict response-size
budget.

Lidl search remains positive-only: a miss is not product absence.

#### Final production-proven retail architecture

The active six-retailer model after the device probe is:

1. **Mercadona — GREEN**
   - search: warehouse Algolia;
   - identity: SKU + exact first-party JSON + EAN.

2. **Masymas / Juan Fornés — GREEN search / AMBER refresh**
   - search: first-party Aktios/TOL REST;
   - identity: numeric product id + EAN already present in search records;
   - remaining: exact publication-time price/availability refresh proof.

3. **ALDI España — GREEN**
   - search: peninsula Algolia;
   - identity: article/object id + brand + sales unit + exact first-party page.

4. **Consum — GREEN**
   - search: first-party REST;
   - identity: product id + exact REST EAN.

5. **DIA España — GREEN only in retailer-first mode**
   - generic search: excluded after production HTTP 403;
   - candidate discovery: official award/category pages/exact SKU;
   - identity/refresh: exact SSR product page.

6. **Lidl España — GREEN/POSITIVE-ONLY**
   - search: first-party JSON;
   - identity: stable product URL/id + exact page;
   - broad queries avoided because of response size and incomplete web
     assortment.

No Carrefour contract and no browser runtime are required.

#### Retail-side research gate status

The production-device candidate-discovery gate is now **PASSED** for the
potential ADR 0085 architecture. The remaining retailer-side sub-gate is only
Masymas exact current offer refresh for publication time.

Remaining uncertainty is no longer "can the phone search the local retailers?"
It is now primarily content-yield and source-discovery economics:

- how many semantically unique award nominations produce exact local-retailer
  matches per rolling year;
- how much OCU/retailer-first material can replenish the pool;
- how often package-equivalent SKUs can be safely grouped;
- whether the measured ready-event runway can approach the desired three-day
  cadence without lowering evidence standards.

ADR 0085 should therefore remain Proposed until a broader automated read-only
award-winner -> retailer dry-run demonstrates sustainable ready-pool yield.


### Content-yield expansion findings — 27 September 2026

#### OCU: 69 food comparators, but the old >=85 gate is not neutral

OCU's current public comparator index lists 69 Alimentación comparators:
https://www.ocu.org/todas-las-informaciones/comparadores

The list spans many supermarket-relevant categories, including gazpacho,
salmorejo, canned tuna, milk, coffee capsules, ground coffee, ordinary beer,
0.0 beer, AOVE, semi-cured cheese, Greek yoghurt, mussels, sardines, tortilla,
pizza, turrón, dark chocolate, eggs, frozen hake and others.

A broad current-result check shows that the source-native
`Mejor del Análisis` title does **not** imply >=85/100.

Current/recent examples visible in OCU's own indexed product/report surfaces:

- Realfooding gazpacho: 90/100;
- Hacendado fresh salmorejo: 70/100;
- AOVE current comparator top quality: 93/100;
- coffee capsules top: 85/100;
- ordinary lager comparator top: 80/100;
- 0.0 beer top products: 84/100;
- whole UHT milk top products: 79/100;
- ground coffee top products: around 81/100;
- semi-cured cheese top: 70/100;
- frozen hake top example: 74/100;
- some current turrón subtypes: 64-86/100.

OCU explicitly defines `Mejor del Análisis` as the best of the products
compared. It also states that comparators are not static: depending on category
they update every 15-30 days or one/more times per year.

Architecture implication:

The historical prototype rule `OCU overall score >=85` is an **editorial
quality floor**, not part of OCU's nomination semantics.

Before ADR 0085 is accepted, choose explicitly between:

1. **nomination-first policy**: accept source-native Mejor del Análisis when the
   result is at least OCU's positive quality band and publish the exact score;
2. **elite-score policy**: retain >=85, knowingly discarding many valid
   supermarket category winners.

Do not silently keep >=85 while claiming the system selects the best product in
each nomination.

No runtime rule is changed by this research.

#### OCU freshness needs a real source-cycle date

OCU comparator page titles can look current while some underlying food studies
originate from older testing cycles. Price data may also update independently
from laboratory results.

The autonomous adapter therefore needs two distinct notions:

- **analysis/result cycle**: when the tested ranking/result was established;
- **retail refresh time**: current product/price availability.

A refreshed price must never make an old laboratory ranking look newly tested.

The event source-cycle key should follow the ranking/result revision, not the
page crawl date or current price date.

A future freshness rule should be explicit rather than inferred from the URL
title. Old results should not re-enter a new annual diversity round unless OCU
actually publishes a new ranking/revision.

#### Sabor del Año 2026 is a potentially high-yield supermarket source

The official Sabor del Año methodology is especially aligned with the desired
article format:

- products are evaluated blind;
- panel: 80 habitual consumers of the product category;
- monadic tasting in individual booths;
- five 0-10 criteria: taste, appearance, smell, texture and overall
  satisfaction;
- award requires both >6/10 and the highest score in the product category.

Official methodology:
https://www.saboresyconsumidores.com/metodologia

The official 2026 winners surface exists at:
https://www.saboresyconsumidores.com/2026

The public rendered winner catalogue is image-heavy, so it is not yet proven as
a no-OCR autonomous source.

Independent current reporting identifies 89 recognised food products in the
2026 edition, including highly supermarket-relevant brands/products such as:

- Central Lechera Asturiana UHT milk range;
- DIA natural yoghurt, burrata and cheesecake;
- Lidl fresh salmon, entrecôte and sirloin;
- Campofrío cooked ham/turkey products;
- Navidul jamón/paleta de cebo ibérico;
- Martiko premium smoked salmon;
- Lipton flavours;
- Pepsi Zero flavour variants;
- Hellmann's Gran Mayonesa;
- Quesos Cerrato Umami;
- Princesa Amandine potatoes.

This makes Sabor del Año potentially much higher-yield than global cheese/wine
competitions if exact official product/category identity can be obtained without
OCR.

Next source-side probe must inspect the official 2026 page HTML/embedded data for
product names, alt text, structured JSON, image metadata or first-party API
literals. If exact winners/categories are only pixels, do not add OCR merely
for this source; use retailer-first leads and explicit first-party/authority
confirmation instead.

#### World Beer Awards: Spanish country/style winners may be high-yield

Current 2026 official World Beer Awards result pages expose explicit Spanish
Country Winner titles in multiple consumer-meaningful styles.

Examples found in official 2026 pages:

- International Lager — Spain Country Winner: Ambar Especial;
- Classic Pilsener — Spain Country Winner: Mahou Sin Filtrar;
- Dortmunder — Spain Country Winner: Estrella Levante Reserva 60;
- Dark Lager — Spain Country Winner: Maestra Dunkel;
- Amber/Dark Kellerbier-Rotbier — Spain Country Winner: Santa Amber;
- No/Low Alcohol IPA — Spain Country Winner: Arriaca IPA Sin;
- No/Low Alcohol Speciality — Spain Country Winner: Tropical con limón.

These are materially more supermarket-oriented than many IWC champion wines and
therefore deserve a dedicated retail-yield pass.

Do not create events from every Gold/Silver/Bronze beer. Use only explicit
Country Winner / World's Best semantic nominations admitted by the source
adapter.



### Source/content-yield production probe — 27 September 2026

A second read-only probe was run on the actual Redmi/Termux production device.
The repository HEAD remained unchanged, `state/product_awards.json` stayed
absent and the crontab hash stayed identical.

#### Masymas exact offer refresh is fully proven

Exact Masymas product detail returned HTTP 200 JSON.

For product id 2034 / EAN 8411700011302:

- product name: `Bebida Láctea Omega3 Con Nueces`;
- ordinary price: 1.95 EUR;
- current offer price: 1.69 EUR;
- unit price metadata: litre;
- purchase bounds were also present.

For product id 9079 / EAN 8424465845242:

- product name: `Pan 100% Integral`;
- current price: 1.90 EUR;
- unit-price metadata: 9.74 EUR/kg.

This closes the Masymas retailer chain:

`search -> id/EAN -> exact detail -> current price`.

Masymas is now fully GREEN for the future autonomous retailer architecture.

#### OCU comparator/product HTML findings

Eight representative OCU comparator pages were fetched anonymously:

- milk;
- ordinary beer;
- alcohol-free beer;
- coffee capsules;
- AOVE;
- canned tuna;
- salmorejo;
- semi-cured cheese.

All returned HTTP 200. Typical HTML size was about 350-366 KiB.

Observed raw-page characteristics were strikingly uniform:

- zero literal `MEJOR DEL ANÁLISIS` occurrences in the raw comparator HTML;
- repeated generic laboratory markers;
- many generic `score`/`quality` strings;
- no simple `productId` field;
- many unrelated global navigation/comparator links.

The first-party script set included ProductSelectors listing/filter/sorter
managers. A bounded inspection found generic `api/`, `product`, `quality`,
`result` and `score` markers but no reviewed stable endpoint literal that
can yet be used as a direct comparator winner feed.

Known OCU product pages for RAM milk, Mahou 0.0, L'OR Ristretto and Carbonell
AOVE all returned HTTP 200 and contained the laboratory marker, but a simple
anonymous raw-HTML parser did not see the visible winner badge/score.

Important interpretation:

- OCU's public/indexed content definitely contains source-native scores and
  winner badges;
- the obvious raw HTML path is not a cheap direct winner API;
- a more focused inspection of listing component configuration/AJAX requests is
  justified;
- browser automation is not justified.

#### OCU source-native score distribution challenges the old >=85 gate

Current indexed OCU result surfaces confirm that many legitimate
`Mejor del Análisis` winners score below 85.

Examples already found in current/recent OCU content:

- Hacendado fresh salmorejo: 70/100;
- top semi-cured cheese: 70/100;
- whole milk leaders: high-70s;
- ordinary beer leaders: around 80/100;
- ground coffee leaders: low-80s;
- 0.0 beer leaders: 84/100;
- some turrón subtype winners: 64/100;
- other categories such as cava/gazpacho/AOVE can exceed 85.

Therefore `>=85` should be documented as an editorial elite threshold, not a
definition of "winner".

This matters directly to annual content yield.

#### Sabor del Año official 2026 page

The official 2026 page returned:

- HTTP 200;
- about 680 KiB HTML.

Simple token counts in the raw payload included:

- `DIA`: 280 occurrences;
- `CAMPOFR`: 1;
- `BURRATA`: 1.

But a normal `img` parser surfaced only ten ordinary image tags and their
alt/title values did not enumerate the winners.

The page is a Wix application. The first bounded generic bundle inspection
found standard Wix runtime/public telemetry literals but no obvious direct
winner endpoint.

This is still promising: the mismatch between rich text tokens in the page
payload and sparse normal image tags suggests winner information may exist in
serialized Wix page/component data.

A focused no-OCR probe should print bounded context around known winner tokens
and enumerate JSON/application data blocks rather than scanning generic Wix
runtime bundles.

#### External corroboration for Sabor del Año 2026 content yield

Current trade reporting lists 89 recognised food products in the 2026 edition,
including highly supermarket-relevant products from DIA, Lidl, Central Lechera
Asturiana, Campofrío, Navidul, Martiko, Hellmann's, Pepsi/Lipton and others.

This is not sufficient as autonomous award authority by itself, but it confirms
that Sabor del Año has potentially excellent local-supermarket yield if the
official first-party page can be decoded deterministically without OCR.

#### World Beer Awards Spain yield direction

Current 2026 official World Beer Awards pages expose multiple Spanish Country
Winner products in mass-market styles, including examples from Ambar, Mahou,
Estrella Levante and other brands with materially higher supermarket presence
than many global wine champions.

This source deserves a dedicated local-retailer dry-run before large IWC/CMB
expansion.



### Focused OCU/Wix source-contract probe — 27 September 2026

A further read-only production-device probe clarified both OCU and Sabor del Año
without browser automation or OCR.

#### OCU current comparator pages render usable product lists in raw HTML

Current OCU canned-mussels/sardines comparator pages returned HTTP 200 and
server-rendered product cards.

Observed raw headings included exact commercial names from multiple target
retailers, for example:

- `SAL DE PLATA (ALDI) MEJILLONES EN ESCABECHE`;
- `MARI MARINERA (DIA) MEJILLONES EN ESCABECHE`;
- `CONSUM MEJILLONES EN ESCABECHE`;
- `HACENDADO (MERCADONA) MEJILLONES DE CHILE EN ESCABECHE`;
- `HACENDADO (MERCADONA) Aceite de oliva` for sardines;
- `NIXE (LIDL) Aceite de oliva`;
- `SAL DE PLATA (ALDI) Aceite de oliva`;
- `MARI MARINERA (DIA) Aceite de oliva`.

The pages expose stable OCU product-detail URLs and product ids such as
`124201_124211`, `124201_124223`, `124201_124206`,
`124201_124221`, and sardine ids in the `571_...` family.

This means the comparator source can deterministically enumerate the tested
product universe without a browser.

#### OCU editorial/report pages expose winner semantics and scores in text

Current report/news pages are much richer than the anonymous product-detail
HTML for source-native winner semantics.

Examples observed directly in raw HTML:

- canned tuna report explicitly says Sal de Plata (ALDI) and Hacendado
  (Mercadona) stand out for the best quality/value and explicitly mentions
  `Mejor del Análisis` / `Compra Maestra`;
- ground-coffee report explicitly names Fortaleza blend at 79/100 and Lavazza
  Crema e Gusto Classico natural coffee at 81/100 as the best products of their
  respective coffee subtypes;
- sardines report exposes current product-level scores including Hacendado
  65/100 and other products;
- mussels report explicitly names the standout Eroski Galicia product and
  mentions Sal de Plata among the strongest value/quality products.

This supports a possible low-complexity OCU architecture:
comparator page -> tested product universe,
editorial/report page -> source-native winner semantics/method facts,
retailer -> current exact offer.

Do not assume every comparator has a matching editorial report until measured.

#### OCU frontend exposes a real ProductSelectorsAPI contract

Raw comparator HTML exposes the listing component configuration:

- component/controller: `PsfProductListing`;
- action: `RefreshProductListing`;
- load-more action: `LoadMoreProducts`;
- main page id;
- current page / total pages;
- stable product ids;
- search/filter/sorter component configuration.

The first-party JavaScript reveals that ProductSelectors requests are built as:

`/ProductSelectorsAPI/<controller>/<action>/<scID>`

with ordinary AJAX POST helpers.

This is strong evidence that OCU has a browser-free internal transport layer.
The exact POST body still needs one focused read-only reproduction before it can
be admitted as a runtime contract.

#### Sabor del Año official Wix warmup data is machine-readable

The official 2026 page contains a `wix-warmup-data` JSON script block.

A parsed first-party JSON walk recovered real gallery metadata with no OCR.
Examples:

- `campofrio.jpg`;
- `dia-yogur.jpg`;
- `dia-burrata.jpg`;
- `dia-tarta.jpg`;
- `cantero-de-letur.jpg`.

Each gallery item also carries a stable item id and media id.

This disproves the earlier fear that first-party Sabor del Año discovery is
necessarily image-pixel-only. The official source has at least a structured
media lead layer.

However, current inspected metadata often has empty title/alt fields and some
filenames are brand-only or product-family-only. Therefore the full gallery must
be enumerated and classified before deciding whether official metadata alone can
establish exact commercial product + semantic nomination.

If many items remain ambiguous, the preferred fallback is a reviewed textual
secondary authority plus first-party official media confirmation, not OCR.

#### Next factual gates

1. OCU: reproduce one `ProductSelectorsAPI/PsfProductListing` POST and inspect
   whether quality/ranking/card state is available cheaply.
2. Sabor del Año: enumerate every 2026 gallery filename/item id/media id and
   classify exact-product vs brand-only ambiguity.
3. Measure how many OCU food comparators expose a usable editorial/report winner
   page versus requiring ProductSelectors quality data.
4. Only after these source contracts are known, perform the large annual
   nomination -> retailer yield run.


#### OCU score gate: source-native winner can be below 85

Current indexed OCU food pages provide direct evidence that
`Mejor del Análisis` is not synonymous with an >=85 numerical score.

Examples:

- Hacendado chocolate-crunch turrón: 64/100, `BUENA CALIDAD`,
  `MEJOR DEL ANÁLISIS`, and `COMPRA MAESTRA`;
- Carvel semicurado cheese: 70/100, `MUY BUENA CALIDAD`,
  `MEJOR DEL ANÁLISIS`;
- La Turronería Turrón de Alicante: 85/100, `MUY BUENA CALIDAD`,
  `MEJOR DEL ANÁLISIS`.

Therefore the historical >=85 rule is strictly a project editorial gate.

Before implementation, the annual-yield study must calculate at least two
scenarios:

1. source-native nomination eligibility, requiring `Mejor del Análisis` and no
   negative OCU quality band;
2. elite-only eligibility, additionally requiring >=85.

The final policy should be chosen from measured content quality/runway tradeoff,
not assumed in advance.


### Deep OCU/Wix contract refinement — 27 September 2026

A deeper read-only production-device probe produced two source-side
simplifications.

#### OCU raw HTML already contains the complete tested-product search universe

The current canned-mussels comparator exposes an application/json script:

`Psf-Search-ProductFamily-SerializedSearchUniverse_<id>`

The JSON contains every searchable tested product with fields such as:

- `label`;
- product-detail relative URL;
- old/non-tested/outdated flags.

Observed examples include ALDI Sal de Plata, DIA Mari Marinera, Mercadona
Hacendado, Consum and other products.

This is better than expected: autonomous enumeration of the products tested in a
comparison does not require a browser or even the listing AJAX endpoint.

The listing cards additionally expose:

- `data-psfListGridItemProductId`;
- exact compare title and image;
- per-product `PsfQualityBox`;
- per-product `qualityboxGuid`;
- laboratory-tested marker.

The raw anonymous score area itself remains closed behind `Ver resultados`, so
the smallest remaining OCU question is how the quality box/winner score is
fetched.

#### OCU listing POST is optional unless it improves evidence/cost

First-party JavaScript confirms:

- `RefreshComponent` builds a URL with `getApiUrl`;
- the body is `MapToPsfListingRenderRequest()` serialized as JSON;
- transport is an ordinary POST returning HTML;
- `LoadMore` uses the same model.

This means the internal transport is browser-free, but the runtime should not
use it merely because it exists. The initial HTML already contains the product
universe.

A future probe should compare:

1. direct initial comparator HTML + smallest quality-box call;
2. ProductSelectors listing POST;

and keep whichever is simpler and cheaper.

#### Sabor del Año page-model identity is now exact

The official 2026 Wix route exposes:

- page id `dfya4`;
- page URI `2026`;
- page JSON file name
  `9fcf1c_8c74f66eaa969705860f7686ced42fc9_268`.

The current generic `galleryData.items` recursive walk returned zero gallery
objects, so component nesting has changed or the relevant data is loaded through
another Wix page-model structure.

This zero result must not override the prior first-party evidence of
winner-related media filenames such as DIA/Campofrío assets.

The next read-only probe should:

- extract Wix topology/base URL if published;
- request the exact 2026 page JSON/static model using the published filename;
- enumerate every file/media name from both page HTML and page-model JSON;
- classify filename specificity;
- avoid OCR.



### Public OCU feed strategy and Producto del Año source — 27 September 2026

#### OCU transport policy: API-first if the frontend call is anonymously public

The deep production probe exposed two facts at once:

- some comparator quality UI is labelled `Contenido Exclusivo`;
- the first-party frontend also exposes structured ProductSelectors and
  quality-box transport.

The correct engineering conclusion is not to reject the API. DOM parsing is the
more fragile contract. The next probe must reproduce the exact frontend request
and classify its access semantics.

If the call works anonymously without subscriber credentials or entitlement
tokens and returns the fields already exposed to the public frontend, that
first-party API should be the **primary runtime contract**.

If the call requires authenticated/member access, the bot must not bypass that
control and should use public report/comparator surfaces instead.

This distinction gives the best stability without assuming that every visible
frontend endpoint is fair game.

#### OCU has public dated discovery feeds

Official first-party feeds currently expose:

- `https://www.ocu.org/todas-las-informaciones/informes`;
- `https://www.ocu.org/todas-las-informaciones/noticias`;
- public press-note listing under OCU's organization/press section.

The Informes feed is date ordered and paginated. Current 2026 examples include:

- 07 July 2026 — `Los mejores salmorejos envasados de 2026`;
- 16 March 2026 — a current bebidas vegetales report;
- other food/product analysis reports distributed through the same feed.

The public salmorejo report and press note expose useful article-quality facts
such as:

- 30 products analysed;
- tested supermarket/private-label products;
- expert-cook sensory tasting;
- price collection timing;
- standout products/brands;
- current report date/result cycle.

A practical OCU source adapter can therefore be event-driven rather than
comparator-driven:

1. poll only the first one or two public feed pages on a slow cadence;
2. remember the newest processed report URL/date;
3. inspect only new Alimentación/product-analysis articles;
4. extract explicit public winner/subtype/best-product statements and scores;
5. open the related comparator only to validate product universe, stable OCU
   product identity and laboratory/test context.

This avoids rechecking all 69 comparators and avoids restricted quality data.

The 69 Alimentación comparator index remains valuable as a category manifest and
coverage map, not as a daily polling list.

#### Gran Premio a la Innovación / Producto del Año is a strong new source

Official source:
`https://granpremioalainnovacion.com/productos-ganadores-pda/`

The 2026 page is ordinary structured text: one winner/product range followed by
one explicit category.

Current human food/beverage examples include:

- Celta + Proteína — Bebidas Lácteas;
- Takis Blue Heat — Snacks;
- Extratiernos / Croquetería ELPOZO — Cárnicos + Platos Preparados;
- Lipton Ice Tea Mango Maracuyá — Refrescos de Té;
- Dinamic Protein — Barritas Proteicas;
- Salsas del Chef La Palma Coolinary — Salsas;
- Serpis Nature — Aceitunas;
- Maison Perrier Chic — Combinados sin alcohol;
- Nescafé Latte Baileys — Cafés Refrigerados;
- Kong Strong Hydration — Refrescos;
- 1954 Premium Gourmet — Embutidos;
- Charcutería Selecta Legado Ibérico — Charcutería Ibérica;
- Blédina — Alimentación Infantil.

The organizer's own FAQ/process pages say:

- more than 10,000 representative consumers vote;
- candidates are grouped into homogeneous categories;
- each candidate also receives a product test with 100 people from its target;
- the highest-scoring product in the category is elected Producto del Año.

This is not a general quality medal. It is a consumer-selected **innovation**
award. Preserve that semantic dimension explicitly.

Because the page is clean text, edition-scoped and mass-market-oriented, this
source is technically cheaper than Sabor del Año and likely higher retailer
yield than specialist/global wine/cheese competitions.

It should receive a high-priority retail-yield sample before adding more complex
source adapters.

#### Producto Marca Distribuidor

The same organizer has a separate official private-label winner programme/page.
The currently indexed page prominently exposes 2025 winners; historical pages
show exact category/product pairs including retailer private labels.

This programme may be especially valuable when a current edition contains
Lidl/DIA or another active retailer's own-brand product, because retail identity
is already strongly hinted.

Do not infer a 2026 distributor edition before an official current-year page is
actually published.

#### PLMA: technically strong, low current local priority

PLMA's 2026 International Salute to Excellence Awards are high-quality
structured awards:

- roughly 600 submitted products;
- 67/69 retailers from 27 countries depending on the official summary version;
- expert judging of concept, taste/aroma/texture, packaging/presentation and
  value;
- 106 winners from 46 retailers.

However, the official 2026 retailer summary shows only a small Spanish presence,
with EROSKI clearly represented and no strong evidence yet of our six active
Spanish retailer chains among the Spanish winners.

Therefore PLMA is worth monitoring opportunistically but does not justify a
dedicated adapter before higher-yield Spanish sources are exhausted.



#### OCU architecture correction: API stability vs DOM stability

A first-party API consumed by OCU's own frontend is expected to be more robust
against layout redesigns than CSS/DOM parsing. The prospective adapter should
therefore maintain a transport hierarchy:

1. anonymous first-party API/JSON contract;
2. serialized JSON already embedded in the page;
3. minimal HTML fallback;
4. public editorial/report page for narrative/methodology enrichment.

Health monitoring should fingerprint HTTP status, content type and a small set
of required schema fields. A schema drift in the primary API should raise one
admin alert and allow the fallback layer to continue if it still validates the
same source cycle/product identity.

Do not create dual parsing complexity unless the fallback is materially simpler:
the fallback exists for graceful degradation, not to maintain two full
independent implementations forever.


#### Exact OCU quality-box frontend request shape

Inspection of OCU's current first-party frontend code identifies the exact
anonymous quality-box transport used when a user clicks `Ver resultados`.

Controller/action:

- controller: `PsfQualityBoxes`;
- action: `RenderQualityBox`.

URL construction follows the common ProductSelectors rule:

`<routingPrefix>/ProductSelectorsAPI/PsfQualityBoxes/RenderQualityBox/<scID>`

The frontend submits ordinary POST form data with:

- `productId`;
- `productPhoenixId`;
- `mainPageId`;
- `isModel`;
- `qualityboxGuid`;
- `redirectUrl`.

The comparator HTML already exposes all corresponding values except
`redirectUrl`, which is simply the current page path.

No authorization header, subscriber token or explicit session object appears in
the JavaScript call itself. Whether the server returns full quality data or an
anonymous login/teaser response must be proven with a cookie-free production
probe.

This is the decisive OCU API gate:

- full score/badge anonymously -> use first-party API as primary runtime
  contract;
- teaser/login only -> do not attempt to bypass entitlement; retain public
  report/embedded-data fallback.


#### OCU anonymous quality API result: stable transport, gated score

The exact first-party OCU frontend call was reproduced from the production
Redmi/Termux device:

`POST /ProductSelectorsAPI/PsfQualityBoxes/RenderQualityBox/<scID>`

The request used the exact frontend fields and deliberately sent:

- no Cookie header;
- no Authorization header;
- no subscriber token.

Five products from the canned-mussels comparator were tested, including ALDI
Sal de Plata and several non-target brands.

For every product the endpoint returned:

- HTTP 200;
- `application/json`;
- `Valid = true`;
- one deterministic HTML update for the requested quality-box id.

The rendered anonymous content consistently exposed:

- `Analizado en el laboratorio`;
- `Calidad global OCU`;
- the scale labels `Mala / Media / Buena / Muy Buena`;
- evaluation dimensions such as labeling, nutrition, oil quality, heavy metals,
  freshness, biotoxins, hygiene and tasting;
- analysis date `marzo 2026`;
- `Acceso exclusivo`, join CTA and existing-member login CTA.

It did **not** expose:

- numeric product score;
- current quality band for the product;
- `Mejor del Análisis`;
- `Compra Maestra`.

The response was effectively the same entitlement teaser for all five products.

Conclusion:

- OCU's anonymous quality-box API is a valid, stable first-party public
  methodology/context source;
- winner/score/rank data are server-side entitlement-gated;
- do not attempt to derive or bypass those protected fields;
- public OCU report/news/press pages remain the winner/score authority;
- `SerializedSearchUniverse` remains the cheap deterministic tested-product
  identity source.

This result also clarifies the robustness strategy: API-first remains desirable
for fields the API actually exposes anonymously, while protected result fields
must come from separate public authority surfaces.

#### OCU annual public-feed probe had a parser-quality issue

The earlier annual-source inventory successfully fetched 11 OCU `Informes`
pages and observed food-analysis material, but its link collector also captured
social-share URLs (Twitter/Facebook/WhatsApp) as if they were report links.

Therefore the reported `68 unique food report links` is **not a valid annual
report count** and must not be used for yield forecasting.

A corrected inventory must:

- accept only canonical `https://www.ocu.org/alimentacion/...` links;
- reject social/share hosts and query-wrapped OCU URLs;
- canonicalize duplicates;
- extract the article's own publication/update date;
- classify actual comparative product analyses separately from generic food
  advice/news.

This corrected feed inventory is required before estimating OCU READY/year.


#### Premio Cinco Estrellas: good methodology, insufficient SKU specificity

A further high-yield-source search identified Premio Cinco Estrellas España
2026.

Its official methodology is consumer based and comparatively strong:

- category study to define relevant purchase attributes;
- satisfaction survey with 100 clients/users of the evaluated brand/product;
- representative national market study for brand trust and innovation;
- winner must have the highest overall result in the category and meet the
  minimum required score of 7/10.

The 2026 food/beverage categories include plant drinks, cured meats, coffee
brand, beer, gazpacho, canned legumes, Moscatel wine and yoghurt.

However, the official winner surface is primarily **brand/category**, for
example:

- Estrella Galicia — Cerveza;
- Garcia Millán — Gazpacho;
- Luengo — Legumbres en Conserva;
- Pastoret — Yogures;
- Alpro — Bebidas Vegetales.

This is insufficient to transfer the award to an arbitrary current retail SKU
when the brand has multiple products/variants.

Architecture decision:

- do not add a dedicated Premio Cinco Estrellas product adapter;
- admit an event only if a future official category result identifies an exact
  commercial product/range strongly enough to pass the normal identity gate;
- brand-only category wins remain non-publishable for Product Awards.

This exclusion is intentional and protects the system from award-to-SKU
over-attribution.


### Quantitative 20-event retail-yield pilot — 27 September 2026

A read-only production-device pilot tested 20 current award events:

- 13 Producto del Año 2026 food/beverage manufacturer awards;
- 7 World Beer Awards 2026 Spanish style winners.

The probe deliberately printed candidates only and did not automatically call
them exact matches.

#### Corrected OCU inventory result

The corrected OCU Informes crawl removed share-host noise.

Across the 11 tested public Informes pages it found:

- 17 canonical OCU food article URLs;
- 11 canonical food articles with a 2026 publication date;
- 6 heuristic likely comparative-analysis articles.

The six heuristic analysis candidates included current salmorejo, milk,
plant-based drinks, kefir, Greek yoghurt and kombucha material.

This is an `Informes`-feed measurement, not proof that OCU published only six
food comparisons in all public surfaces in 2026. Noticias/press/comparator
updates can add additional source events.

The old `68 unique food report links` number is retired.

#### Strong exact-retail lower bound from the 20-event sample

At least six events already have strong exact identity evidence:

**Celta +Proteína / Producto del Año 2026**
- Consum search returned EAN 8414044004122 (coffee) and
  8414044004108 (cacao);
- current Leche Celta product/logistics material identifies those EANs as
  Celta +Proteína 250 ml variants;
- Leche Celta explicitly states the awarded 2026 range includes the 1 L milk
  plus coffee and cacao 250 ml shakes.

**Takis Blue Heat / Producto del Año 2026**
- Consum returned EAN 8412600047163;
- current Consum exact page identifies that EAN as Takis Blue Heat 130 g.

**ELPOZO ExtraTiernos / Producto del Año 2026**
- Consum returned EAN 8410843064220 for `Escalopín Lomo Adob. Extratierno`;
- current exact product sources identify the EAN as ELPOZO ExtraTiernos
  escalopín de lomo;
- ELPOZO's own 2026 award announcement states that the awarded ExtraTiernos
  range specifically includes pork/beef escalopines and solomillos.

**Nescafé Latte Baileys / Producto del Año 2026**
- Masymas and Consum both returned EAN 8435257073224;
- current product catalogues identify the EAN as Nescafé Latte/Shakissimo
  Baileys;
- current producer/award communications explicitly identify Nescafé Latte
  Baileys as Producto del Año 2026.

**Ambar Especial / World Beer Awards 2026**
- Consum returned EAN 84107015;
- current Consum and other retailer data identify EAN 84107015 as
  `Ambar Cerveza Especial`.

**Mahou Sin Filtrar / World Beer Awards 2026**
- Masymas returned EAN 8411327010153;
- current exact retailer data identifies it as Mahou 5 Estrellas Sin Filtrar.

This yields a strict measured lower bound of **6/20 = 30%** before query-variant
recovery or full exact-detail follow-up.

#### Important false positives caught by exact identity

The pilot also demonstrates why fuzzy/name-only acceptance is unsafe.

**Arriaca IPA Sin**
- Masymas returned EAN 8436571780034 as `Cerveza Artesana Ipa`;
- current exact product data identifies EAN 8436571780034 as TYRIS IPA, not
  Arriaca IPA Sin;
- reject.

**Maestra Dunkel**
- Masymas returned EAN 8411327002004 as `Cerveza Maestra`;
- current exact product sources identify EAN 8411327002004 as Mahou Maestra
  Doble Lúpulo;
- it is not Maestra Dunkel;
- reject.

**Estrella Levante Reserva 60**
- Mercadona returned generic Estrella de Levante products;
- the award is specifically for Reserva 60, a distinct 6.2% Dortmunder;
- generic Estrella de Levante identity cannot inherit the award;
- unresolved until an exact Reserva 60 retail SKU is found.

The same fail-closed rule rejects generic/fuzzy candidates for Santa Amber,
Tropical con Limón and other unresolved events.

#### World Beer Awards 2026 source-truth refinement

Current 2026 Spanish award evidence confirms the relevant award set but source
semantics should be stored exactly:

- Estrella de Levante Reserva 60 is stronger than a national title: it is
  `World's Best Dortmunder`;
- Arriaca IPA Sin is explicitly a 2026 Gold / Spain Country Winner for No & Low
  Alcohol IPA;
- Santa Amber is explicitly Gold / Spain Country Winner for
  Amber/Dark Kellerbier & Rotbier;
- current Foods & Wines from Spain reporting lists the 2026 Spanish gold set
  including Mahou Sin Filtrar, Maestra Dunkel, Ambar Especial, Arriaca IPA Sin,
  Tropical con Limón and Reserva 60.

Do not infer `Country Winner` merely from an old WBA product history page; bind
each event to its 2026 edition evidence.

#### Retail cost measurement

The pilot used 105 retail-search requests and 10,832,968 response bytes.

Breakdown:

| Retailer | Requests | Bytes | Strong exact events visible in pilot |
| --- | ---: | ---: | ---: |
| Mercadona | 21 | 73,963 | 0 |
| Masymas | 21 | 1,027,345 | 2 |
| Consum | 21 | 12,530 | 5 |
| ALDI | 21 | 34,748 | 0 |
| Lidl | 21 | 9,684,382 | 0 |

The strong-event counts overlap: Nescafé appears in both Masymas and Consum.

This sample is heavily manufacturer-brand oriented, so it is **not** evidence
that Mercadona/ALDI are globally low-yield. Those two retailers remain important
for OCU/private-label and retailer-specific awards.

It is strong evidence that Lidl generic search is poor default economics for
unhinted manufacturer award winners: about 89% of total payload, no exact event
in this sample, and search misses are not authoritative.

#### Search routing implication

Use source/product-aware routing rather than a fixed local-retailer order.

Manufacturer-brand awards:
- explicit source hint first;
- Consum then Masymas are high-priority based on this sample;
- cheap Mercadona/ALDI searches may follow;
- Lidl generic search is conditional/final, not default.

Retailer/private-label awards:
- route directly to the retailer named by the award source.

Retailer-first Lidl/DIA awards:
- use the retailer award lead and exact product page;
- avoid generic discovery if it adds no identity value.

#### Next quantitative gate

The 30% figure is only a lower bound because the first pilot used long search
phrases that visibly caused fuzzy/OR result drift.

The next probe should:

1. exact-detail confirm the six strong events on the active retailer itself;
2. retry unresolved manufacturer awards using deterministic query variants:
   exact brand, distinctive product token, then product family;
3. search Consum and Masymas first;
4. skip generic Lidl unless a product-specific reason exists;
5. measure recovered exact matches and request bytes;
6. then freeze the query strategy before scaling to larger source families.


#### Source-defined award ranges improve yield without adding slots

The quantitative pilot reveals a useful award-subject distinction.

Some current Producto del Año 2026 awards are explicitly awarded to a producer
range rather than one package SKU.

**Celta +Proteína**
The producer explicitly states that the awarded 2026 range consists of:

- UHT skimmed lactose-free +Proteína milk, 1 L;
- +Proteína coffee shake, 250 ml;
- +Proteína cacao shake, 250 ml.

Current Consum exact retail pages expose the two shake members by exact EAN:

- coffee: 8414044004122;
- cacao: 8414044004108.

The award therefore creates one `Bebidas Lácteas / innovation` event, while
either exact member can establish current retail eligibility.

**ELPOZO ranges**
ELPOZO's own 2026 award announcement explicitly identifies included references:

- ExtraTiernos: pork/beef escalopines and solomillos;
- La Croquetería: jamón ibérico and chicken croquettes;
- 1954 Premium Gourmet Natural Sin Aditivos: cooked ham, turkey breast and
  chicken breast;
- Charcutería Selecta Legado Ibérico: Delicias Ibéricas and Mortadela Ibérica.

The first pilot found an exact ExtraTiernos current candidate, but its long
range-name queries did not properly search the source-certified 1954/Legado
members. The next recovery probe must search the explicit member names rather
than treating the range title as one literal retail product.

Rule:

- one source-defined range = one award event/publication slot;
- search only authority-listed members;
- one exact member is enough to make the event retail-eligible;
- additional current members may be shown in the article;
- never multiply annual slot count by the number of range members.

#### DIA production role is narrower than previously proposed

The quantitative Redmi probe attempted the official DIA
`/l/productos-premiados-dia` page and received HTTP 403.

Combined with the earlier HTTP 403 from generic DIA search, while exact product
pages still return HTTP 200, the current production-device capability is:

- discovery/search: NOT proven anonymously;
- exact known SKU/page validation: proven.

Therefore DIA should be treated as **exact-validation-only** in the prospective
runtime unless another anonymous first-party discovery contract is later
demonstrated.

External/web research may still use DIA's award page to understand source
content, but the Termux architecture cannot depend on that surface today.

#### Lidl generic search should be conditional, not default

In the 20-event manufacturer-brand pilot, Lidl search used 9,684,382 bytes from
10,832,968 total retail bytes (~89%) and yielded no strict exact event.

This does not make Lidl an unimportant retailer. It means its generic search is
bad default economics for unhinted manufacturer awards.

Keep Lidl strong for:

- Lidl/private-label award leads;
- exact known Lidl products;
- source-provided Lidl hints;
- targeted fallback where a distinctive exact product term exists.

Do not query Lidl generically for every nomination.


## Production-verified retailer, media and publication contracts - 28 September 2026

This section supersedes earlier speculative retailer and presentation assumptions
where they conflict with the production probes below.

### Retailer lookup contracts

The production Redmi/Termux probes establish retailer-specific contracts rather
than one universal search strategy.

**Mercadona**
- exact-name Algolia discovery can recover a stable product id;
- EAN search returned no hit in the tested contract;
- textual product-id search returned no hit;
- direct `/api/products/<id>/` detail is cheap and returns exact product
  identity, EAN, price data and photos;
- runtime shape: exact-name discovery once -> save id -> direct REST refresh.

**Consum**
- exact-name search with `limit=1` can recover the internal product id;
- EAN search returned no result in the tested contract;
- textual internal-id search returned no result;
- direct detail by saved id returns exact EAN, product data, price data and
  media;
- runtime shape: exact-name discovery once -> validate -> save id -> direct
  detail refresh.

**Masymas / Juan Fornes**
- exact EAN search works for the validated Nescafe Latte Baileys control;
- exact-name search also works;
- textual internal-id search is unsafe: query `14523` returned an unrelated
  noodle product;
- direct detail by saved id works;
- runtime shape when EAN is known: EAN discovery -> exact EAN validation ->
  save id -> direct detail refresh.

**ALDI Espana**
- exact-name Algolia discovery works;
- direct Algolia object refresh by saved objectID works and is very small;
- tested search hits did not expose EAN, so EAN-search support remains
  unproven and must not be assumed;
- ALDI product objects expose availability, price and first-party media assets.

**DIA Espana**
- the first-party JSON search-back endpoint returned HTTP 403 from production
  Termux with multiple normal user-agent profiles;
- repeated WAF circumvention is intentionally out of scope;
- runtime discovery through that endpoint is therefore unavailable today;
- known exact first-party product pages may still be useful outside that
  blocked discovery contract, but no automatic DIA publication should depend
  on an unproven current-price refresh.

**Lidl Espana**
- generic `q/api/search` is not a trustworthy exact-discovery contract;
- an exact positive query, the KONG query, and an impossible query all returned
  superficially valid search responses, while the latter two surfaced
  unrelated first products;
- HTTP 200, `numFound` and first-result presence are therefore never identity
  evidence;
- generic Lidl search is too expensive to run for every award event;
- source-provided Lidl hints and known exact Lidl pages remain useful.

These contracts preserve the rule that a search hit is only a candidate and a
search miss is not proof of retail absence.

### First-party product-photo contracts

Photo acquisition does not require a separate heavy image-search subsystem for
the retailers already production-probed.

**Mercadona**
- the same exact REST detail used for identity and price exposes `photos[]`;
- the tested product returned three photographs;
- every photo exposed `zoom` 3600x3600, `regular` 600x600 and `thumbnail`
  300x300 variants;
- preferred publication image: the first exact-product `regular` image.

**Consum**
- direct product detail exposes both `productData.imageURL` and `media[]`;
- five validated award products were tested and all five had exact first-party
  product images: Celta +Proteina Cafe, Takis Blue Heat, ELPOZO ExtraTiernos,
  Nescafe Latte Baileys and Ambar Especial;
- all five exact-detail EANs matched the expected award-product EANs;
- no extra search request is needed to obtain the image.

**Masymas**
- direct detail exposes a first-party product image;
- the returned URL used a 135x135 path, but the same exact image was verified
  at 300x300 with HTTP 200;
- 600x600 and 800x800 variants returned HTTP 404;
- preferred publication image: validated 300x300 first-party variant.

**ALDI**
- direct product objects expose `assets[]`;
- product-pack media must be selected, preferably `type=primary`, instead of
  badges or attribute icons;
- the exact NALTROS Brut object was verified with objectID `190300`, current
  product data and a first-party primary pack image;
- the deleted NALTROS publication therefore lacked a photo because the old
  runtime did not extract media, not because ALDI lacked a usable image.

Photo fallback policy:
1. exact first-party retailer product media;
2. exact official manufacturer or award-organizer media;
3. text-only publication.

Automatic third-party image catalogues are excluded because stale packaging or
a neighboring SKU can silently break identity.

### Lidl exact-product and media evidence

Current first-party Lidl pages close most of the previous KONG identity/media
gap.

The official exact product page for `KONG STRONG Hydration Blue Raspberry`
identifies the brand and exact product and exposes multiple first-party images.
Those images include the exact Blue Raspberry bottle and group images showing
Tropical, Blue Raspberry and Ice Pop variants.

A separate official Lidl range/weekly page labels `Kong Strong Hydration` as
`Producto del Ano 2026`, exposes product imagery and a 500 ml package, and
shows a 0.99 EUR regular / 0.79 EUR promotional price. However, that page
explicitly scopes the offer to 26 January through 1 February and says store
availability can vary. That old campaign price must not be reused as a current
September price.

The official Producto del Ano 2026 winner page independently lists
`KONG STRONG HYDRATION` in the soft-drinks category.

Therefore:
- Lidl award identity: strong enough for a reviewed range event;
- exact first-party product image: proven;
- generic Lidl search: still unsuitable as primary discovery;
- current September retailer price: still requires an exact current production
  contract before automatic publication.

### Editorial publication contract

The final Product Awards output is an editorial mini-article, not a field card.

Required presentation behavior:
- use a natural headline with the actual award/result;
- write coherent human-readable paragraphs that explain what the product is,
  who evaluated or awarded it, what it achieved, why the result is notable,
  and the current verified store price;
- expand an unfamiliar organization on first mention, for example
  `OCU - испанская Организация потребителей и пользователей
  (Organizacion de Consumidores y Usuarios)`, then use the abbreviation;
- do not include award-source links in the final publication;
- do not include retailer product links in the final publication;
- do not use links as a substitute for explaining the result;
- keep unique product/result facts visible;
- place repeated methodology and award-process boilerplate inside a Telegram
  collapsed expandable quotation so readers can open it only if interested;
- include an exact product photo whenever a verified first-party or official
  image is available;
- preserve the normal group footer.

Methodology content must remain source-grounded. The renderer may omit a detail
that is unavailable, but it must not invent tasting panels, laboratory checks,
sample counts, nutrition labels or award semantics.

### Telegram transport research

Telegram Bot API 10.1 introduced Rich Messages and `sendRichMessage`.
Bot API 10.2 added explicit rich-message media and media blocks. Bot API 10.3
added expandable/collapsible block quotations.

The current API contract supports:
- up to 32768 UTF-8 characters in rich-message text;
- separate HTTP/HTTPS image blocks;
- HTML rich-message formatting;
- `<blockquote expandable>...</blockquote>`;
- silent delivery through `disable_notification`.

This fits the required Product Awards UX much better than `sendPhoto`, whose
caption path in the current bot is limited to 1024 characters.

The existing repository Telegram client already has a generic JSON Bot API
transport, so a future Product Awards implementation should need only a small
`send_rich_message` wrapper rather than a new networking stack.

A live client rendering test is still required before implementation acceptance
because the API contract is proven but the exact visual appearance in the
Guardamar group/client has not yet been operator-approved.

### Remaining research gates

Only two material gates remain before freezing implementation design:

1. Lidl current-price contract:
   test exact KONG member queries / exact current product data on the production
   device and determine whether a current price and availability can be
   refreshed without generic broad search.

2. Telegram visual acceptance:
   send one explicitly marked temporary Rich Message containing an exact
   first-party product photo, several editorial paragraphs and a collapsed
   methodology block, inspect it in the real Telegram client, then delete it.

No additional broad retailer crawling is justified unless either of those gates
reveals a new concrete problem.


### Rich Message mobile visual validation and photo-quality gate

A live private-chat Rich Message was rendered in Telegram on the operator's
phone using the first-party Lidl KONG STRONG Hydration Blue Raspberry image.

The Rich Message transport itself behaved as intended:
- photo and long editorial text appeared in one message;
- the expandable methodology block rendered as a collapsed block that can be
  opened by the reader;
- the message layout remained readable on mobile.

The first Lidl product image did **not** meet the visual quality bar. On mobile,
the bottle occupied only a very small fraction of the image area, the product
label was unreadable, and the image looked like an indistinct blue bottle. This
is a publication-quality failure even though the source and SKU identity were
correct.

The failure is mainly a framing/source-detail problem, not just Telegram
compression. Upscaling a tiny bottle centered inside a large white canvas would
not restore missing label detail.

Photo-quality rule:
- prefer the highest-resolution exact-SKU first-party image available;
- reject an image when the product occupies too little of the frame or the
  identifying label/packaging is not visually recognizable on a normal phone;
- if the source has excessive empty margins, a deterministic crop may remove
  empty/transparent background and preserve a modest margin around the product;
- do not treat simple upscaling as quality recovery;
- if the retailer exact-SKU image is inadequate, try exact official
  manufacturer or award-organizer media;
- if no sufficiently recognizable official image exists, publish text-only
  rather than a misleading or illegible thumbnail.

For Lidl KONG specifically, the exact page exposes three first-party images.
The first is the weak isolated-bottle asset used in the test. The second shows
three KONG STRONG variants and fills the frame better; it is suitable only when
the publication subject is the awarded range, not when the story claims to be
about one exact flavor. The third is another range/lifestyle composition and
requires the same subject-scope check.

Implementation implication:
photo selection needs a small quality gate after identity validation. The gate
should consider both source resolution and product occupancy/recognizability,
not merely whether an image URL exists.


### Editorial simplification: no per-product taxonomy

Do not introduce a separate persistent taxonomy for product kinds or local-name
translation modes merely to improve headlines.

The renderer should use product/category wording that is already present in
validated source facts when it is clear and useful. If the source does not
provide a simple trustworthy type, use the product name without inventing or
maintaining another classification layer.

Examples:
- a source that clearly identifies Ambar Especial as beer may render
  "пиво Ambar Especial";
- a source that clearly identifies NALTROS Brut as cava/sparkling wine may use
  that wording naturally, but preserving the local word `cava` is optional
  editorial polish, not a new data-model requirement;
- names such as gazpacho or salmorejo do not require a separate translation
  taxonomy.

This deliberately avoids per-SKU `product_kind_ru`, `product_kind_local` or
translation-mode fields. The Termux runtime should remain small and derive
wording from already fetched facts rather than carrying editorial metadata that
does not improve identity or publication safety.
