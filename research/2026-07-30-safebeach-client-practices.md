# SafeBeach public-client practices checked on 2026-07-30

Primary references:

- Guardamar municipal environment page:
  <https://www.guardamardelsegura.es/medio-ambiente-2/>
- SafeBeach public Guardamar page:
  <https://info.safebeach.es/guardamar-del-segura>
- SafeBeach feature description:
  <https://www.safebeach.es/como-funciona-safe-beach/>
- SafeBeach service information:
  <https://safebeach.es/contratalo/>
- SafeBeach legal notice:
  <https://www.safebeach.es/aviso-legal/>

Observed public-page behavior:

- The municipality links to SafeBeach for Guardamar beach status.
- One HTML response embeds `window.SB_MARKERS`; JavaScript execution and a
  second data request are unnecessary.
- The response observed on 2026-07-29 was about 90 KB, `text/html`, and marked
  `no-cache, private`, with no `ETag` or `Last-Modified`.
- The page exposes a local calendar date and per-record activity,
  service-ended state, last update time, flag text/color, temperature, wind,
  waves, and jellyfish fields.
- The Guardamar page exposed six named zones: Centre / Babilònia, La Roqueta,
  Vivers, Montcaio, Camp, and les Ortigues. This observation supports the
  bounded named-fallback order but is not treated as a permanent schema
  guarantee.
- SafeBeach describes lifeguard input as real-time information but also states
  that its mobile tool can collect data without connectivity. Therefore an
  available page is not proof that every beach has synchronized current data.
- The embedded public schema has no published compatibility or rate-limit
  contract. The separately advertised REST API is not used by this MVP.

Project implication:

Use one bounded same-day HTML request per scheduled invocation, validate only
the selected fields, preserve partial valid beaches, reject contradictions,
and retain neither cookies nor past statuses. The external five-minute schedule
is the retry mechanism.
