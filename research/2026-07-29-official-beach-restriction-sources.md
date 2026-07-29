# Official Beach Restriction Sources

## Question

Can Cruz Roja or NÁYADE provide a lightweight official fallback for current
Guardamar beach closures, bathing restrictions, and safety precautions?

## Sources checked

- Cruz Roja Española, Estado de las Playas:
  `https://www.cruzroja.es/appjv/consPlayas/consultaInicio.do`
- Ministerio de Sanidad, NÁYADE citizen portal:
  `https://nayadeciudadano.sanidad.gob.es/Splayas/ciudadano/`
- Ayuntamiento de Guardamar beach-management specification:
  `https://www.guardamardelsegura.es/wp-content/uploads/2023/10/20231005_9-PROYECTO-DE-GESTION-SOCORRISMO-PLAYAS.pdf`
- Ayuntamiento and Generalitat reports concerning the July 2023 short
  pollution incident at Centre and Els Tossals.

Accessed on 29 July 2026.

## Cruz Roja findings

- The public service is live and exposes small server-rendered HTML plus JSON
  autocomplete endpoints.
- Its current active list for Comunidad Valenciana contains 23 beaches.
- Guardamar del Segura is absent. The similarly named result is Guardamar de
  la Safor in Valencia and must not be confused with this project area.
- The service therefore cannot currently confirm a flag, closure, reason, or
  reopening for Guardamar del Segura.
- An older municipal beach-management specification says that a Guardamar
  coordinator would enter the daily flag around 10:00 in the Cruz Roja
  application. That historical operating statement does not prove current
  publication: the live 2026 public list is authoritative for availability.

## NÁYADE findings

- NÁYADE lists all seven official Guardamar zones for the 2026 season:
  Centre, Babilonia, La Roqueta, Ortigues-Campo, Tusales, Vivers, and Moncaio.
- The citizen portal provides sampling dates, *E. coli*, intestinal
  enterococci, and a short observation such as `Zona Apta para el baño`.
- The access method is stateful server-rendered HTML with form POSTs. It is
  technically possible with the Python standard library, but not a stable
  structured API.
- On 29 July 2026, the newest displayed sample for every Guardamar zone was
  dated 25 June 2026. The data was therefore more than one month behind the
  current date.
- The known Centre and Els Tossals closure of 27 July 2023 and reopening about
  24 hours later is not represented as an unsafe record in the visible NÁYADE
  sampling history. Adjacent stored samples remain marked suitable.
- NÁYADE is useful for official history and general water-quality context, but
  the citizen view cannot be trusted as a timely closure-state feed.

## Operational incident pattern

The July 2023 pollution case shows the required lifecycle:

1. The authority receives an anomalous result.
2. Named beaches are explicitly closed and red flags are raised.
3. Follow-up samples are taken.
4. A separate official message reopens the beaches after acceptable results.

This lifecycle can complete inside one day, faster than weekly reports and
public sampling histories. A bot must preserve the explicit closure until an
equally explicit reopening, but only when both messages can be dated and
matched safely.

## Official mayor-channel findings

The bounded public search view of `https://t.me/s/AlcaldeGuardamar` contains
consistent explicit safety notices. Historical examples include:

- red flag and bathing prohibited because of strong rip currents;
- red flag because of high sea, strong drag, waves, and currents;
- named Centre and Tossals pollution closure after official samples;
- red flag and bathing prohibited after blue-dragon detections, with named
  discovery beaches and safety instructions;
- later yellow-flag notices that explicitly say bathing is permitted or that
  the special surveillance operation has ended.

The messages carry trustworthy Telegram publication timestamps. The decisive
Spanish phrases are direct and repetitive enough to detect deterministically:
`BANDERA ROJA`, `PROHIBIDO EL BAÑO`, `BANDERA AMARILLA`, and
`PERMITIDO EL BAÑO`. Reasons and named beaches vary and must not be invented.

For the accepted same-morning role, the ordinary latest-post page is
sufficient: the bot considers only explicit transitions published after its
07:30 message. If that bounded page cannot prove a qualifying timestamp and
phrase, the Mayor contribution is omitted. The bot does not carry an older
restriction forward or infer how a later flag changes a differently scoped
notice. User-facing reasons are limited to a small reviewed vocabulary.

## Recommendation

- Reject Cruz Roja as a current Guardamar fallback because the live service
  does not list the municipality.
- Do not use NÁYADE as an operative closure or caution source. It may be
  reconsidered later for non-urgent historical context, which is outside the
  Morning Digest need.
- Keep SafeBeach for current structured beach operations when available.
- Accept the official `@AlcaldeGuardamar` channel as the best candidate for a
  narrow deterministic restriction lifecycle, subject to the open product
  rules above.
- Do not infer safety from the absence of a notice, an old `Zona Apta` record,
  or a weekly PDF.

Confidence is high for the Cruz Roja and NÁYADE rejection and high that the
mayor channel can support explicit red/allowed transitions without broad AI
interpretation.
