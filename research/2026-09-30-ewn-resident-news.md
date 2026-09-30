# Euro Weekly News resident-impact discovery research

Date: 2026-09-30

## Question

Can the bot use one lightweight external editorial feed to discover practical
Spain-wide changes for residents without becoming a general news aggregator,
overloading Termux, or treating a newspaper as the factual source?

The target editorial class is broader than legislation alone. Useful candidates
include material changes to everyday rules, prices, public services, transport,
housing, taxes, benefits, motoring, immigration/residency administration,
health access, and announced disruptions such as significant strikes. Ordinary
crime, celebrity, sport, human-interest, party-political commentary, and remote
regional incidents are not the product.

## Source reviewed

Discovery source:

- Euro Weekly News, `News from Spain`
- category page: `https://euroweeklynews.com/news/spain/`
- RSS endpoint: `https://euroweeklynews.com/news/spain/feed/`

The RSS endpoint exists and responds as XML. It is suitable for one bounded
standard-library read; no browser or JavaScript is needed.

EWN is **not** accepted as a factual publication source. It is only a discovery
surface that can point the bot at a topic and, when the article itself links to
one, a first-party source.

## Editorial sample

A manual review of 112 recent `News from Spain` items, covering roughly
16-30 September 2026, found three broad groups:

- about 17 items (~15%) were clear matches for the desired practical-news
  product;
- about 22 items (~20%) were plausible candidates needing editorial judgment;
- about 73 items (~65%) were ordinary news/noise for this bot.

The useful group repeatedly contained the same practical classes: DGT/rule
changes, Renfe/customer-service changes, housing/rent rules, fuel/energy
measures, grants, social rights, autonomous-worker measures, and other changes
that alter what a resident can do, must do, pay, or expect.

This is enough signal to justify a narrow classifier, but not enough to publish
the feed directly.

## Production-like probe on 2026-09-30

The first bounded production probe ran on the validated merged code before cron
installation. It used the latest eight RSS items and made one real
classification request.

Observed decisions:

- housing/rent package: relevant / high;
- October fuel support: relevant / high;
- Renfe ticket-sales change: relevant / normal;
- Ibiza tourist death: rejected;
- Guardia Civil cash/crime story: rejected;
- pending housing vote: relevant / high;
- Valencia torrential-rain story: incorrectly accepted / high;
- pet emergency-card lifestyle story: rejected.

The classifier therefore separated the intended practical-news group from
crime/accident/lifestyle noise reasonably well, but the weather item exposed an
important overlap with existing bot responsibilities. Current weather, storms,
floods, wildfire, earthquake, beach/sea, local emergency and road-closure
status are now explicitly excluded from resident-news discovery because those
domains already have dedicated official-source workflows. RSS items carrying a
`Spain Weather`/weather category are also discarded deterministically before
AI.

The same probe exposed a parser assumption: the live EWN story page did not
wrap the visible story in an HTML `<article>` element. The original parser
therefore failed with `EWN article body was not found` before it could inspect
the links. The production cron remained disabled and no Telegram message was
sent.

Live inspection also showed that not every approved-host link is useful. The
housing article linked to general landing/index pages for La Moncloa, Congreso
and BOE, while the Renfe article linked directly to Renfe's specific
announcement. The corrected parser therefore:

- starts the story region after the first visible `h1`;
- stops before Comments/Continue Reading or the footer;
- does not require an `<article>` wrapper;
- rejects generic official landing/index URLs;
- selects the first **specific** approved first-party URL in story order;
- still relies on the final composition call to confirm that the selected
  first-party text actually supports the discovered topic.

This correction keeps the original no-search boundary. A useful story with only
generic official landing links is intentionally omitted rather than triggering
a web search or extra AI research.


## First-party-link finding

The important simplification is that relevant EWN articles often already link
to the responsible first-party source in the article body.

Observed examples:

1. **Renfe sales-system change**
   - EWN article links directly to
     `grupo.renfe.com/.../renfe-transforma-sistema-de-venta`.
   - The Renfe page states the phased 28 October rollout and 25 January
     completion and explains the passenger-facing changes.

2. **Road-rule change**
   - EWN article links directly to `www.dgt.es` and to the applicable
     `www.boe.es` Real Decreto.
   - The first contextual official link is DGT, which is the better
     resident-facing source for the traffic-rule notice; BOE remains the legal
     text.

3. **Fuel-discount article on 29 September**
   - The reviewed EWN version contained an external media link but no suitable
     first-party government/BOE link.
   - Under the proposed MVP this article must **not** auto-publish. This is an
     intentional coverage tradeoff that avoids adding search, web-wide
     discovery, or factual reliance on EWN.

Therefore the MVP does not search the web for a source. It extracts only links
already present in the EWN article and fails closed when no approved first-party
link exists.

## Primary-source policy

A public post may be generated only from a fetched first-party source.

Initial accepted host families are deliberately narrow:

- Spanish government/public law: `.gob.es`, `boe.es`;
- national legislature: `congreso.es`, `senado.es`;
- Generalitat Valenciana: `gva.es` and subdomains;
- DGT: `dgt.es`;
- Renfe: `renfe.com` and `grupo.renfe.com`;
- public employment/social-security surfaces: `sepe.es`,
  `seg-social.es`;
- AEMET: `aemet.es`;
- large national union first-party announcements for strikes:
  `ccoo.es`, `ugt.es`, `cgt.es`.

The list is code-reviewed and may grow only from observed missed candidates.
There is no generic trust of arbitrary external domains.

For an EWN article containing several accepted links, inspect only the visible
story region (after the first `h1`, before comments/continue-reading/footer)
and use the earliest **specific** accepted first-party link. Generic home/index
pages are not sufficient evidence. This naturally keeps a direct DGT
explanation or Renfe announcement when present, while avoiding an unrelated
government landing page.

## AI contract

### Discovery classification

At each scheduled run:

- fetch one bounded RSS document;
- consider at most 8 unseen items;
- send only each item's stable ID, title, and a description capped to 500
  characters;
- one structured AI call classifies the whole batch;
- store every classification result in a small bounded state;
- no article HTML is fetched for rejected items.

The classifier asks one narrow question: does this item report a concrete
change, pending decision, first-party announcement, or material disruption
relevant to residents of Guardamar? Spain-wide changes and changes applying to
Comunitat Valenciana/Alicante/Guardamar qualify; locality-specific stories
elsewhere require a clear nationwide consequence. It must reject ordinary
crime, celebrity, sport, entertainment, human-interest, opinion, routine
political statements, and geographically remote local stories without wider
relevance. Current weather/storm/flood/wildfire/earthquake/beach/local-emergency
and road-closure status are excluded because existing official-source workflows
already own those operational domains.

A pending vote/proposal can be relevant; the model must not require that a
measure already be in force.

### Final editorial composition

For one eligible candidate per invocation:

- fetch the EWN article only to extract first-party links and discovery context;
- choose one accepted first-party link deterministically;
- fetch that source with strict host/content/size limits;
- send the first-party text plus a short EWN discovery context to one
  structured AI call;
- the same call first verifies that the selected first-party text actually
  supports the discovered topic and comes from an appropriate responsible
  first-party source rather than merely commenting on someone else's decision;
- the first-party text is the factual authority; EWN context may explain why
  the topic matters but may not supply unsupported facts.

The output is not a literal translation. It is a short, natural Russian
Telegram editorial note:

- one concise headline;
- 2-4 narrative paragraphs;
- moderate thematic emoji: one heading emoji and at most two additional
  thematic emoji inside the prose when they improve scanning;
- explain what changed/is proposed, practical effect, timing and meaningful
  caveats naturally rather than as a questionnaire;
- preserve proposal/approval/effective/strike/disruption status;
- no invented advice or causal claims;
- neutral and non-partisan for political/policy material;
- one deterministic source link at the end, labelled with the first-party
  organization, not EWN.

## Provider/resource decision

Keep the existing provider direction:

- Gemini `gemini-3.5-flash-lite` remains primary;
- Groq `openai/gpt-oss-120b` is permitted as fallback for the two new bounded
  text operations only;
- no direct Groq-first route, third provider, quota manager, retries, or local
  model.

Production-like budget:

- 3 one-shot checks/day;
- max 1 batch-classification call/run;
- max 1 final-composition call/run;
- therefore max 6 primary AI calls/day before rare provider fallback;
- max 8 RSS items/classification batch;
- max 500 description characters/item;
- max 8,000 normalized first-party source characters for composition;
- max one public article/run.

The phone performs only XML/HTML parsing and bounded HTTPS. No inference runs on
Android. No new Python dependency, browser, PDF, OCR, database, embeddings,
daemon, or worker is required.

## State/lifecycle

Use one small atomic JSON file. On the first valid RSS read, seed current items
silently so deployment cannot replay old news.

Keep a bounded recent item set (maximum 128 records, with old terminal records
pruned). Item states are small lifecycle markers such as `eligible`,
`dropped`, `source_missing`, `uncertain`, and `published`; no raw RSS,
article HTML, official HTML, or generated history is stored.

At most one eligible item is attempted per run. Unsent eligible items may remain
for a later normal invocation, but stale candidates are dropped rather than
forming an unbounded queue.

Ambiguous Telegram delivery is marked uncertain and never automatically resent.

## Proposed schedule

Use three quiet one-shot slots in `Europe/Madrid`:

- 11:11
- 15:11
- 18:11

These avoid the known hourly :19 CCE watcher, :30 Hidraqua check, :37 traffic
watcher, :55 earthquake watcher, 14:20 product-award slot, and the principal
morning/evening publication windows.

## Decision

Proceed with the narrow first-party-grounded MVP.

Do **not** implement a general news engine. Do not add another discovery source,
web search, arbitrary-domain crawling, or EWN-only public claims. Coverage loss
when EWN does not provide a first-party link is accepted to keep the feature
small, trustworthy, and reversible.
