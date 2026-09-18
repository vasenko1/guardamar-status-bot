# Cinema metadata and synopsis audit — 2026-09-18

Status: implementation-ready and covered by the full unit suite on the feature
branch. This note records the source contract and safety decisions so the cinema
pipeline is not rediscovered from scratch later.

## Existing source surfaces

No new source was added.

### Turismo Guardamar

The already-fetched monthly cultural agenda has a dedicated `CINE` section.
Current September 2026 rows consistently expose:

- explicit weekday/date/time;
- explicit venue;
- film title;
- parenthetical `director, year. country`;
- age rating;
- genre;
- duration in minutes;
- admission wording.

Current examples cover Monday library screenings and Friday screenings at the
music school.

This is the primary deterministic cinema-metadata source.

### Todo Cultura Vega Baja

The existing supplemental WordPress source contains richer prose, including
explicit synopsis paragraphs, original titles and cast information.

The bot already splits a municipal programme into dated sections and then into
`event_rows` identified by an explicit start time. Synopsis enrichment must
operate on those rows, never on an entire WordPress page or URL.

Historical/current examples showed that TodoCultura pages may contain unrelated
or duplicated synopsis material. A Gremlins example contains another film's
synopsis later in the same content. Therefore page-level synopsis selection is
unsafe.

## Structured cinema rule

The existing deterministic `extract_official_cinema()` is generalized from
"Monday + Biblioteca only" to every explicit row in the official `CINE`
section.

A row is accepted only when:

1. its Spanish/Valencian weekday is recognized;
2. the declared weekday equals the actual calendar weekday;
3. date is inside the accepted monthly window;
4. place/title metadata match the known compact row grammar;
5. the venue is map-safe;
6. duration, when present, is in the existing safe range.

Monday library screenings retain the established
`Cine de los Lunes` presentation. Other verified cinema rows render with a
cinema marker.

The existing `details`, `duration_minutes` and `audience_label` fields
carry the metadata; no cinema-specific Event subclass or schema is introduced.

## Deliberately omitted film credits

The official parenthetical block also contains `director, year. country`, and
TodoCultura may contain original title and cast.

These facts are deliberately not added to the morning digest. The user-facing
gap being solved is genre, duration, age rating and a short source-backed
synopsis. Adding credits would require extra parsing/presentation policy without
improving that core use case.

The current Ali occurrence also demonstrates a real year conflict:
Turismo/Agenda Guardamar state 1973 while TodoCultura states 1974. The bot must
not silently resolve it.

## Safe synopsis rule

TodoCultura synopsis is optional enrichment and never establishes that an event
is cinema by itself.

A synopsis may be attached only when:

1. the target event is already verified as `turismo_cinema`;
2. TodoCultura produced an existing deterministic `event_row`;
3. event date matches exactly;
4. event start time matches exactly;
5. title overlap strongly identifies the same occurrence;
6. the row contains exactly one explicit `La sinopsis ... es la/el siguiente:`
   marker;
7. exactly one best synopsis survives matching.

Zero markers, multiple markers, tied/conflicting synopses or weak identity
produce no teaser.

### Excerpt policy

The bot does not ask a model to summarize synopsis text.

It creates a bounded source excerpt deterministically:

- normalize whitespace;
- reject trivial text under 20 characters;
- keep the whole synopsis when it is at most 220 source characters;
- otherwise start with the first complete sentence;
- when that sentence is too short to carry useful meaning (<80 characters),
  append following complete sentences while staying within 220 characters;
- if one sentence itself is too long, cut at a word boundary near 210
  characters and preserve an ellipsis.

This rule was selected after checking:
- a normal informative first sentence;
- a long one-sentence synopsis;
- a multi-sentence synopsis;
- a synopsis whose first sentence is only a location/year setup;
- a short synopsis;
- content containing two synopsis markers.

## Translation

Only the already-bounded excerpt is translated.

Cinema synopsis uses a dedicated translation-only contract:
- preserve every factual claim, named entity and uncertainty;
- no summarizing;
- no added facts;
- no inference;
- no embellishment;
- no merging of details;
- preserve a source ellipsis.

It has its own cache identity `municipal_cinema_teaser`. Existing non-cinema
teaser translation behavior remains unchanged.

If no prepared translation exists, the Russian digest omits the teaser rather
than exposing untranslated Spanish or generating a fallback synopsis.

## Ticket UX

Ticket rendering remains one shared path.

- free + no URL -> `Бесплатно`;
- free + URL -> `Бесплатно · Получить билет`, with the whole label linked;
- paid + URL -> the existing paid ticket label;
- unknown price + URL -> `Билеты`.

No cinema-specific ticket branch exists.

## Venue normalization

For cinema rows only, `Escuela de Música` and `Escola de Música` are
canonicalized to `Escola de Música`. The shared venue normalizer is left
unchanged so unrelated concerts, talks and other event types do not acquire a
cinema-driven behavior change.

## Expected Ali presentation

When current source facts and prepared translations are present, the occurrence
can render approximately as:

```text
19:00 — 🎬 Все мы зовемся Али
Драма • 93 мин • 13+
<bounded translated source synopsis>
📍 Escola de Música
🎟 Бесплатно · Получить билет
```

The year is intentionally absent because the official source set conflicts.

## Non-cinema blast radius

The implementation intentionally leaves non-cinema extraction and rendering
unchanged except for one previously approved shared UX rule:

- any free event with an explicit ticket URL renders the whole label
  `Бесплатно · Получить билет` as one link.

Cinema synopsis translation is optional. Failure of the dedicated synopsis
translator is logged and the teaser is omitted; it must not block translation
or caching of ordinary event titles.

TodoCultura `PARSER_VERSION` advances from 12 to 13 once so already-processed
rows can expose their existing `event_rows` to the new synopsis matcher. This
uses the source's existing bounded migration mechanism: at most the existing
candidate/program limits are reprocessed, and no new polling loop or source is
introduced. The tradeoff is one bounded re-read/re-extraction of current
TodoCultura programme rows after deployment.

## Rejected designs

Do not:
- fetch IMDb/TMDB/other movie databases;
- scrape the ticket page for movie metadata;
- summarize a whole TodoCultura page with an LLM;
- take the first page-wide synopsis;
- trust a TodoCultura URL/occurrence date as sufficient identity;
- invent a synopsis when none is safely matched;
- add a generic confidence-scoring framework;
- add a cinema-specific persistence layer.

The implementation stays within the existing event model, source fetches,
translation cache and renderer.
