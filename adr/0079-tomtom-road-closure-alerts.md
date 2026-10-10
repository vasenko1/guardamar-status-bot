# ADR 0079: TomTom road and lane closure alerts

## Status

Accepted for production implementation

## Context

Guardamar municipal sources do not expose a complete public operational feed of
current street-closure permits. The Mayor channel and public Sede/Urbanismo
surfaces miss real closures. A live 23–24 September 2026 experiment showed that
TomTom Orbis Traffic Incident Details exposes the active Guardamar restriction
on Avenida del Mediterráneo, including exact LineString geometry, source
`from` / `to` boundaries, `present` validity and incident category.

Reverse Geocoding independently resolved the tested geometry to Guardamar del
Segura and successfully exposed `municipalitySubdivision` for El Raso,
Pòrtic Mediterrani, Pinomar and Bonavista. El Edén did not expose a subdivision,
so subdivision names cannot be required.

The product is not intended to be a general traffic-news feed. Short-lived
accidents, jams, weather and other traffic conditions are out of scope. The
resident need is specifically a road or traffic lane that is closed long enough
to affect normal local movement.

## Decision

- Use TomTom Orbis Traffic Incident Details with one bounded request per hour.
- Query the tested Guardamar-wide bbox
  `-0.7000,38.0250,-0.6200,38.1350`.
- Request `timeValidity=present,future` without an `iconCategories` filter.
  TomTom's category filter applies to the incident's main icon category, while
  a closure may also appear as a secondary `events[].iconCategory`.
- Locally retain only incidents whose main category or secondary event category
  contains `roadClosed` or `laneClosed`; full road closure takes precedence
  over lane closure when both are present.
- The hourly cadence is deliberate. A closure that begins and disappears between
  checks may be missed; this is acceptable because very short restrictions are
  not the target product.
- Accept source probabilities `certain` and `probable`. Do not publish
  `risk_of` or `improbable`.
- Fetch TomTom traffic descriptions in Spanish (`es-ES`).
- Reverse-geocode the incident geometry and publish only when at least the
  midpoint or a boundary point resolves to `Guardamar del Segura`.
- Use `municipalitySubdivision` when present, stripping only the generic
  Urbanización / Urbanització prefix. Never invent a missing urbanization.
- Link the displayed location directly to the incident coordinates in Google
  Maps. House numbers from one reverse-geocoded point are not treated as the
  boundaries of a LineString.
- Treat source `null`, string `"null"`, `none`, `undefined`, empty and
  equivalent sentinel values as missing. Never stringify them into public copy.

## Publication lifecycle

- A newly observed eligible `present` closure publishes immediately.
- When one successful hourly snapshot would otherwise produce two or more
  standalone notifications (new active restrictions or next-day planned
  restrictions), combine them into one traffic summary instead of sending a
  burst of per-street messages. Each included
  incident keeps its own lifecycle markers and stores the same Telegram message
  ID as its reply anchor. Reply-based category changes and confirmed endings
  remain per incident.
- An eligible `future` closure publishes once on the local calendar day before
  its start: "tomorrow ...".
- When that planned incident actually becomes `present`, publish the normal
  active alert.
- An unchanged continuing `present` incident does not create another standalone
  Telegram notification. The hourly monitor keeps its state fresh but remains
  silent until a resident-useful transition occurs.
- Morning Digest may show one compact read-only road-status line so a long-lived
  closure remains visible without producing a daily traffic post. It uses only
  already-announced `present` incidents from the existing traffic state whose
  `last_seen_at` is no more than three hours old. Mirrored TomTom records for the
  same physical segment are collapsed with the same segment identity used by
  traffic batch presentation. No extra TomTom or reverse-geocoding request is
  made for Morning Digest; stale or invalid state is omitted rather than shown.
- A known future `endTime` is only an estimate. If the incident remains
  `present` after that time, present validity wins and the expired estimate is
  omitted from later copy.
- TomTom `properties.id` is treated as a provider identifier, not as the
  durable identity of a physical closure. Before any missing counter advances,
  the monitor reconciles a disappeared active ID with a newly observed ID only
  when the mapping is one-to-one and the source facts identify the same road
  segment: both boundaries are present and equal (or reversed together with
  the geometry), start times differ by no more than two minutes, and both
  geometry endpoints are within five metres.
- A clean provider-ID rotation preserves the existing publication lifecycle and
  Telegram anchor without a new alert. Equivalent IDs that overlap in one
  snapshot are suppressed until a clean handoff; an ambiguous match freezes
  only the affected missing lifecycle for that invocation and publishes
  nothing from the ambiguous replacement set.
- The undocumented `TTR...` suffix observed inside TomTom IDs is diagnostic
  evidence only and is not used as a runtime identity contract.
- One successful snapshot without a previously active physical closure is not
  enough to announce reopening. Two consecutive successful snapshots without
  an exact ID or a reconciled equivalent confirm the local monitor transition.
- A confirmed end of `roadClosed` or `laneClosed` publishes a reply to the
  latest stored alert when possible; if the Telegram anchor no longer exists,
  use the existing standalone fallback. The reopening copy repeats the affected
  segment and, when known, when the restriction began, so it remains
  self-contained even after a long closure.
- If an already announced `future` incident disappears for two successful
  snapshots before becoming present, reply conservatively that the planned
  restriction is no longer shown in current TomTom data; do not claim a
  cancellation without explicit evidence.
- Category transitions between lane and full road closure are resident-useful
  and may publish one reply. Changes only to reason/details, expected end,
  probability, reports, timestamps or small geometry corrections do not create
  a new push. The next normal alert may use the fresher facts.

## Editorial contract

Every active road/lane restriction alert uses the single deterministic title
`🚧 Перекрытие участка дороги`, followed by one natural Russian body
paragraph that distinguishes a full road closure from a lane closure, one
linked location row and the shared
`📣 обЪявления Гуардамар` footer.

Gemini receives only normalized, known source facts and is invoked only when the
lifecycle has already decided that a message is needed. It may connect and
translate the Spanish TomTom details into natural Russian, but it must not invent
a cause, detour, duration, reopening time, number of lanes or event name.
Unknown fields are omitted from the model input. A deterministic Russian
fallback is used if Gemini and its configured fallback are unavailable.

A cause is not inferred from a separate nearby TomTom incident. For example, a
neighboring `roadWorks` record does not prove that a `roadClosed` record is
closed because of those works.

## State and failure policy

Use one small atomic `state/traffic.json` protected by a file lock. Store only
the current/recent incident facts, consecutive-missing count, last daily
publication dates and latest Telegram message ID. A provider-ID handoff rekeys
the existing record in place; it adds no alias table, logical-ID field, raw
history or schema migration. Retain recent records for a bounded period; no
database, raw-response archive, generic notification framework or event history
is introduced.

On TomTom transport/schema failure, invalid nested state, or malformed relevant
closure, publish nothing and never advance the missing counter. Reverse-geocode
new incidents before first publication; refresh a known incident's location only
when another public message is actually due, falling back to the cached verified
location if that refresh fails. Telegram non-idempotent sends use the existing
uncertain-delivery policy: preserve the uncertain marker and stop the current
run, so a network ambiguity cannot cascade into multiple uncertain sends. A
reopening/cancellation reply is sent only when a confirmed prior Telegram
message ID exists.

The Termux monitor runs hourly at minute :37, away from the existing main
monitor checkpoints. With a 31-day month this consumes at most 744 Traffic
Incident Details calls, comfortably below the account's observed 2,500 monthly
allowance.