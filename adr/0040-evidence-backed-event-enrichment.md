# ADR 0040: Evidence-backed event enrichment

## Status

Accepted

## Context

The event pipeline could retain a date, time and short act name while dropping
the facts that explain what the event is. For example, the source described a
benefit concert, its tribute format, beneficiary, price and purchase link, but
the normalized catalog kept only the act and tribute name. Per-event reviewed
corrections fix one occurrence and do not improve future programmes.

## Decision

- Text extraction must produce a self-contained Spanish title of at most 120
  characters. It keeps the explicit event kind and named act or work, plus a
  short explicit tribute, benefit purpose, audience or cause when these are
  stated in the event row.
- Every extracted text event carries one exact contiguous source quotation.
  Normalization accepts the event only when the quotation occurs in the
  bounded input and supports every meaningful title word plus every returned
  date, time and place. Poster extraction sets this field to null and retains
  its existing two-reading agreement contract.
- A lower-priority corroborating event may enrich a sparse title only when it
  preserves at least three quarters of the existing title identity and adds at
  least two meaningful words. It cannot replace a conflicting title.
- Parse admission facts deterministically from the same event-local block in
  the official Turismo HTML and Todo Cultura. Bind an explicit price,
  `entrada libre`, or ticket-only link to its dated event row, and retain a
  purchase URL only from HTTPS Agenda Guardamar or Giglon links present in
  that event or admission paragraph.
- Admission matching needs either two shared meaningful words or one shared
  non-generic word, and uses explicit date and time when available. A title
  such as `Concierto` cannot borrow another concert's price. An admission
  without a session time is withheld when multiple matching sessions exist.
- The collector and snapshot loader use the same exact HTTPS ticket-URL
  policy. User information, explicit ports and unreviewed hosts are rejected
  before persistence.
- Official HTML remains authoritative. Todo Cultura may enrich a matching
  identity, while MUPI may only corroborate or suppress a known conflicting
  poster rendering; it cannot rewrite an HTML title or lend admission facts.
- Persist the verified ticket URL in municipal snapshot version 4 and pass it
  through the existing event renderer. Bounded admission evidence is stored
  with the normalized event and source state. Older snapshot versions remain
  readable. Todo parser version 6 and text extractor version 2 reopen their
  bounded inputs once so deployed catalogs acquire safer facts without
  deleting unrelated state.
- Add no source request, dependency, resident process or morning model call.

## Consequences

Future programme changes can produce compact titles that answer what kind of
event is being advertised, while explicit admission details survive into the
digest. Exact evidence and conservative matching fail closed if the model
adds an unsupported claim or a generic title cannot identify one occurrence.
Unknown ticket platforms remain unlinked until reviewed and allowlisted.

The one-time parser migration can download and structure the already covered
rolling window again. This stays within the existing three-document and
seven-day bounds.

## Alternatives rejected

- Add reviewed text for every incomplete event: correct for emergencies but
  not a maintainable future-event pipeline.
- Store free-form generated descriptions: increases message size and permits
  unsupported editorial copy.
- Accept any external link in an aggregator article: weakens the trust and URL
  policy for a small convenience gain.
- Match admission only by event type: generic labels can leak a price or link
  between same-day events.
