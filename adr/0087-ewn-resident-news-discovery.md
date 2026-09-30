# ADR 0087: EWN discovery with first-party-grounded resident news

## Status

Accepted on 2026-09-30. Implemented by the accompanying change.

## Context

The bot intentionally avoids general news aggregation and uses official,
authoritative sources for public factual claims. The operator nevertheless
identified a useful missing product slice: occasional Spain-wide practical
changes for residents, such as DGT rules, Renfe customer changes, fuel/energy
measures, housing rules, benefits, grants, and material announced disruptions.

Research on 2026-09-30 found that Euro Weekly News (EWN) `News from Spain`
contains enough of this editorial signal to be useful as a discovery surface,
but also substantial crime, human-interest, entertainment, and other noise.
EWN cannot therefore be published directly.

Relevant EWN articles frequently contain direct links to the responsible
first-party source. This allows a small architecture in which EWN discovers a
topic but never supplies the factual basis of the Telegram post.

The target remains a weak Android device in Termux and the project remains
free-AI-only. The feature must not add browser automation, search-engine
queries, heavy dependencies, a database, resident workers, or broad provider
routing.

## Decision

### Product boundary

Add one narrow standalone feature: **resident-impact news**.

It is not a general news feed. Eligible topics must report a concrete practical
change, pending decision, first-party announcement, or material disruption
relevant to residents of Guardamar. Spain-wide measures and measures applying
to Comunitat Valenciana, Alicante, or Guardamar are eligible. Local stories
limited to other autonomous communities or provinces require a clear nationwide
consequence. Examples include rules/obligations, public transport, housing,
taxes, benefits, tariffs, motoring, residency administration, public health
access, and significant announced strikes.

Ordinary crime, celebrity, sport, entertainment, human-interest, routine
party-political statements, and remote local incidents without wider relevance
are out of scope.

A proposal or pending vote may be publishable if its non-final status is
preserved. Publication does not require that a measure already be effective.

### Discovery is not evidence

Use only EWN `News from Spain` RSS as the discovery feed.

EWN text is never an authoritative factual input for a public claim. A
candidate can proceed only when its EWN article contains a direct link to an
approved first-party host. The bot does not search for a missing source.

The selected first-party page supplies the factual source and the public source
link. If there is no accepted first-party link, publication fails closed.

### Bounded collection

Each scheduled invocation:

1. performs one bounded RSS read;
2. silently seeds current entries on the first valid run;
3. classifies at most eight unseen items using title plus at most 500
   description characters in one structured AI request;
4. stores only compact classification/lifecycle state;
5. attempts at most one eligible candidate;
6. fetches that candidate's EWN HTML only to locate first-party links;
7. selects the earliest approved first-party link in article-body order;
8. performs one bounded first-party HTML read;
9. makes at most one final AI composition call;
10. sends at most one Telegram post and exits.

No raw RSS, article HTML, first-party HTML, or AI payload is persisted.

### Source allowlist

The initial first-party host policy is explicit and conservative. It accepts
Spanish government/public-law host families, Congreso/Senado, Generalitat
Valenciana, DGT, Renfe, SEPE, Seguridad Social, AEMET, and the reviewed
national union host families needed for first-party strike announcements.

Unknown domains remain ineligible until reviewed.

### AI scope

Extend the approved AI capability boundary with exactly two bounded text
operations:

1. `classify_resident_news`
2. `compose_resident_news`

Gemini remains primary. Direct Groq `openai/gpt-oss-120b` may be used only as
the existing provider-failure fallback for these operations, subject to the
same structured-output, timeout, no-retry, and double-provider-failure rules in
ADR 0085.

The classifier sees only bounded RSS metadata, not article bodies.

The composer sees bounded first-party text plus bounded discovery context. It
must first confirm that the selected first-party text actually supports the
discovered practical topic; an unrelated/background official link fails
closed. When supported, it must treat first-party text as the factual
authority, preserve whether a measure is proposed/pending/approved/effective or
whether a disruption is only announced, remain politically neutral, and make
no unsupported recommendation.

The output is a natural Russian editorial Telegram note rather than a literal
translation: one concise heading, 2-4 short narrative paragraphs, and moderate
thematic emoji. Code, not the model, appends the escaped first-party source
label and URL.

### Runtime and state

Use the existing standard-library HTTP transport and one small atomic JSON
state file. Add no runtime dependency.

The intended schedule is 11:11, 15:11, and 18:11 Europe/Madrid. Each invocation
is one short-lived process.

Keep at most 128 compact item records. Terminal stale records are pruned.
Unsent eligible candidates remain bounded and expire rather than forming an
unbounded work queue. Ambiguous Telegram delivery is stored as uncertain and is
not resent automatically.

### Failure policy

Every stage is optional and fail-closed:

- RSS failure: no action;
- AI classification failure: no classification is committed;
- EWN article/source-link failure: candidate remains bounded or becomes
  source-missing according to the deterministic failure type;
- unapproved source domain: no publication;
- first-party source failure: no post;
- AI composition failure: no post;
- Telegram ambiguous result: mark uncertain, no automatic resend.

The feature never alters Morning Digest or official operational-source state.

## Consequences

The project gains a small editorial discovery layer without weakening the
official-source promise: public facts still come from the responsible
first-party organization.

The expected normal load is three tiny RSS reads and zero-to-six small AI
requests per day, with only one EWN article and one first-party page fetched for
a selected candidate per run.

Some useful stories will be missed when EWN provides no accepted first-party
link. This is deliberate. Missing coverage is preferable to adding web search,
general crawling, or newspaper-grounded factual publication.

## Rejected alternatives

### Publish EWN directly

Rejected because EWN is an editorial discovery source, not the responsible
authority for the factual claim.

### Search the web for a missing official source

Rejected because it turns a bounded feed adapter into a general research
engine, increases network/AI cost, and complicates provenance.

### Literal article translation

Rejected because a short source-grounded editorial note is more useful and
normally uses fewer output tokens.

### Keyword-only selection

Rejected because the reviewed useful stories span unrelated vocabulary and
would require a growing brittle rule list.

### One AI request per RSS item

Rejected because one bounded batch better matches the low-volume feed and free
AI budget.

### Groq-first news path

Rejected because the existing project policy keeps Gemini primary and the
current fallback transport already satisfies the resilience requirement.

### More discovery feeds

Rejected for the MVP. One source is enough to validate the product without
deduplication or source-ranking complexity.
