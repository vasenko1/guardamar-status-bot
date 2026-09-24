resident-facing details we care about — real service dates, hours, beach
coverage, Semana Santa transition periods, etc. — may still live inside
contract/pliego documents.

Reading a broad procurement feed and then opening contract PDFs is too heavy
for this product when a simpler operational source may eventually appear.

Decision: **keep the existing socorrismo research, but do not add a production
PLACSP monitor now**.

## Municipal works and road closures

Re-evaluated 2026-09-24 after a live Guardamar closure.

The earlier conclusion that no dependable operational source existed is now
superseded. TomTom Orbis Traffic Incident Details returned the real active
Guardamar restriction observed around Avenida del Mediterráneo:

- `roadClosed`, `present`, started 23 September 2026;
- source boundaries Calle Miguel Hernández / Avenida del País Valenciano;
- approximately 56 m of LineString geometry;
- a neighboring `roadWorks` segment was returned separately and is not treated
  as proof of the closure's cause.

A deliberately broad Guardamar-area probe returned only this `roadClosed` and
the neighboring `roadWorks`; reverse geocoding placed both in
`Guardamar del Segura`. Additional probes confirmed subdivision labels for
El Raso, Pòrtic Mediterrani, Pinomar and Bonavista, while El Edén returned no
subdivision. Location logic must therefore use subdivision opportunistically,
not require it.

Municipal follow-up found no matching current public notice in the Mayor
channel, public Sede/Gestiona/Urbanismo or Hidraqua active layer. The municipal
road-closure permit process exists internally, but no suitable anonymous live
permit feed was found. Those surfaces are not production dependencies for this
feature.

Accepted product scope:

- fetch the bounded `present,future` incident snapshot without a main-category
  filter, then retain only incidents whose main or secondary event category
  contains `roadClosed` or `laneClosed`; this avoids missing a closure whose
  primary TomTom category is, for example, road works or an accident;
- one TomTom Traffic Incident Details request per hour;
- `present` closures alert immediately and at most once on each later local
  day while still active;
- `future` closures alert once on the day before their scheduled start and
  again only when they actually become `present`;
- two consecutive successful absences confirm the end and allow a reopening
  reply;
- traffic does not enter Morning Digest;
- Spanish TomTom detail text may be editorially joined into natural Russian by
  the existing Gemini/OpenRouter path only at publication time, with a
  deterministic fallback and strict no-invention prompt;
- every active restriction alert uses the universal title
  `🚧 Перекрытие участка дороги`, exact incident coordinates for the map link,
  and the shared Telegram footer;
- null-like optional source values are dropped, never rendered.

Account analytics observed during the experiment show a 2,500/month Traffic
Incident Details allowance and 20,000/month Reverse Geocoding allowance. Hourly
Traffic polling is at most 744 requests in a 31-day month.

Implementation: `src/telegrambot/traffic.py`, ADR 0079.

Status: **accepted for production implementation**.

## Minimal implementation direction

Prefer small source-specific adapters rather than a generic provider framework:

- suma.py
- municipal-news adapter/module
- blood-donation adapter
- Segura/CHS adapter

Reuse existing orchestration and notification/event pipelines wherever
possible.

Do not add:

- browser automation;
- OCR;
- PDF parsing for these new candidates;
- a database;
- a message broker;
- a provider registry;
- a generic notification framework;
- a new always-on process.

## Suggested next step

Before accepting implementation, run a production Termux probe for the five
preferred sources and record:

- HTTP status;
- redirect chain;
- MIME type;
- compressed/uncompressed response size;
- latency;
- required cookies;
- stable marker for the needed Guardamar data;
- whether one request is sufficient on a no-change day.

The preferred end state is that each source costs roughly one small bounded GET
per scheduled check, and new/detail requests occur only when a list/feed
actually changes.