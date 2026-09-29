# 2026-09-29 — Avanza planner outage and GVA GTFS Guardamar gap

## Question

Why did the accepted Alicante, Elche and Zenia Boulevard timetable cards stop
refreshing after the successful 28 September morning transport sync, and can the
official Generalitat GTFS replace the Avanza/Costa Azul planner?

## Production Avanza evidence

The 05:00 transport sync on 28 September 2026 successfully accepted and stored
live Avanza/Costa Azul schedules. A later diagnostic on 29 September queried
Guardamar -> Alicante for 28, 29 and 30 September through the same public
planner flow:

- planner: `https://regular.autobusing.com/info?empresa=costa-azul&locale=es`;
- form action: `https://regular.autobusing.com/info/horarios`;
- every POST returned HTTP 200 and the same 7,183-byte HTML page;
- the page contained `ESTACION CERRADA TEMPORALMENTE`;
- the page contained none of the requested origin, destination or exact date;
- it contained no schedule table rows;
- the existing strict parser rejected every response as
  `Alicante planner result does not match requested route/date`.

This rules out a one-date calendar boundary, a route-specific Alicante failure,
HTTP 429 and a timeout as explanations for the observed response. It also means
the parser is currently behaving correctly: the returned HTML does not prove a
schedule and must not be accepted.

The same source failure affected the Avanza-backed Alicante, Elche and Zenia
adapters. Orihuela, which uses Bus Sigüenza, refreshed normally.

## Official GVA GTFS re-evaluation

The official Generalitat Valenciana interurban bus GTFS was downloaded again on
29 September 2026. The archive was structurally valid:

- size: 14,114,035 bytes;
- stops: 5,249;
- routes: 263;
- trips: 6,363;
- stop_times: 132,385;
- calendar_dates: 4,557.

The four matched Guardamar del Segura stops were:

- `5090010114` — Pinomar [Guardamar del Segura];
- `5090010115` — N-332 pk 67+300 ascendente - Urb. La Rosa;
- `5090010116` — Estació Autobusos Guardamar del Segura;
- `5090060103` — Guardamar – Restautant Xinés [Guardamar del Segura].

Every one of these stops had **zero linked trips**. No GTFS route name contained
`Guardamar`, no trip in the archive touched any matched Guardamar stop, and
there were zero active Guardamar trips on both 2026-09-29 and 2026-09-30 even
though 394 and 397 service IDs respectively were active.

This is not a matcher or service-calendar miss. The current published GTFS
contains the Guardamar stop records but does not contain usable Guardamar
service topology.

The gap conflicts with the current official CE-704 service description, which
states that the corridor is operational and includes, among others,
Alacant-Guardamar, Elx-Guardamar-Torrevieja and routes through La Zenia.
The GVA dataset itself says that it is generated daily and covers schedules up
to ten days ahead, while also warning that route information may not include
the latest changes.

Official references:

- https://dadesobertes.gva.es/va/dataset/tra-hyr-atmv-horaris-i-rutes
- https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096

## Source decision from this probe

Do **not** use the current GVA GTFS as primary or fallback timetable input for
Guardamar intercity cards. A source that is structurally healthy but silently
contains zero Guardamar trips could turn missing source data into a false
"no service" interpretation.

Keep the existing accepted-snapshot fail-closed behaviour. A rejected live
response must preserve the last verified schedule rather than converting source
absence into cancellation.

This rejection is time-sensitive, not permanent. The GVA GTFS may be
re-evaluated only after a future raw archive actually contains trips linked to
Guardamar del Segura stops.

## New official-host finding

The current official Costa Azul homepage still exposes the interurban timetable
planner, but its links are inconsistent:

- the navigation link `Horarios interurbanos` points to
  `regular.autobusing.com`;
- the main `INFORMACIÓN HORARIOS` call-to-action points to
  `regular.autobusing.es`.

Both GET planner pages currently render the Avanza Movilidad Levante timetable
form. The repository adapter is allowlisted only for `.com`.

This creates a narrow next hypothesis: the operator may have moved or partially
migrated the active planner to `.es`, while the old `.com` endpoint still
renders the form but returns the temporary-closure page on POST.

Official Costa Azul page:

- https://costazul.net/

## Next probe

Before changing application code, issue the same bounded
Guardamar -> Alicante POST for the same exact date against **both**
`regular.autobusing.com` and `regular.autobusing.es`, with independent
cookie jars and otherwise identical fields.

Interpretation:

- `.es` returns a validated route/date/table while `.com` returns
  `ESTACION CERRADA TEMPORALMENTE`: change only the approved planner host and
  add regression coverage;
- both hosts return the temporary-closure page: treat this as an operator-side
  planner outage/configuration state; do not weaken validation or add retries;
- both return valid schedules: the earlier outage was transient; decide whether
  one bounded later attempt is justified only from repeated production
  evidence;
- either host changes form/action/field shape: inspect that exact contract
  before implementation.

No production timetable code should change until this comparison is observed.

## Dual-host production comparison

A production probe then repeated the same bounded Guardamar -> Alicante POST
for 28, 29 and 30 September against both official planner hosts,
`regular.autobusing.com` and `regular.autobusing.es`, using independent cookie
jars and otherwise identical form data.

The result was identical on all six requests:

- initial planner HTML: 6,919 bytes;
- form action: `/info/horarios` on the same host;
- POST result: 7,183 bytes;
- `ESTACION CERRADA TEMPORALMENTE`: present;
- requested origin, destination and exact date: absent;
- schedule table rows: zero;
- strict parser: rejected as route/date mismatch.

Therefore the `.es` hostname is **not** a working replacement for `.com`.
Do not change `PLANNER_HOST` or add a second-host fallback. Both public planner
front doors currently expose the same unavailable backend state.

The temporary-closure wording is also historically known to appear on the
Autobusing family when the online sales/planner backend is unavailable even
while services continue. That evidence is contextual only; the current
production conclusion remains based on the six direct probes above.

## Official app backend candidate

Costa Azul's current official Android/iOS app is a separate candidate source.
The current Android package is `com.embarcadero.costazul`; the public store
listing says it contains urban and interurban lines, stop maps and real-time
arrival predictions. Version 3.2.0 was updated in October 2025.

Official/first-party references:

- https://costazul.net/app-ios-android/
- https://play.google.com/store/apps/details?id=com.embarcadero.costazul
- https://apps.apple.com/es/app/costa-azul/id1156441547

This is useful evidence that Costa Azul/Avanza operates another machine-readable
transport backend independently of the broken Autobusing timetable form.
However, no app endpoint has yet been accepted for runtime. The next research
step is to identify the app's public backend host and request contract, then
probe it read-only for Guardamar interurban data before any architecture or code
change.

The app binary itself must not become a runtime dependency. APK inspection, if
used, is research-only to discover public host/URL strings that the official app
already calls.
