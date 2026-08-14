# Transport content for a possible pinned message

Date checked: 2026-08-14

## Purpose

This is a time-sensitive source investigation for a possible future pinned
transport guide. It records route overlap and stop-address findings. It does
not approve implementation or publication.

## Product question

The first draft grouped buses by route. A more useful design for residents is
to group them first by recognizable place, especially an urbanization, beach,
hospital, university, or transport interchange. Each place must then show all
confirmed services and map points.

## Source hierarchy

1. Ayuntamiento de Guardamar and current Costa Azul / Avanza PDFs for the two
   municipal routes.
2. Current Costa Azul interurban route diagrams for stop sequences and exact
   addresses.
3. Generalitat concession documents for authorized network structure.
4. AliBus only as a discovery and live-data view. Its `I` labels and route
   grouping must not replace the current operator diagrams without validation.

## Municipal route 2

Official diagram:

- https://costazul.net/wp-content/uploads/2026/02/L02_v3-Guardamar.pdf
- https://www.guardamardelsegura.es/wp-content/uploads/2026/04/L02_v3-Guardamar.pdf

Confirmed municipal coverage includes Pinomar, Pórtico Mediterráneo, La Rosa,
El Raso, Campico, El Edén, Los Estaños, the bus-station area, and Polideportivo.

The official diagram lists two El Raso stop addresses:

- stop 807: `Av. El Ras Gran, 4`
- stop 808: `Av. El Ras Gran, 47`

The direction labels previously inferred from route order need a final visual
map check before publication.

### Additional services discovered

The current AliBus route views list both Pinomar and La Rosa on:

- I1, Alicante to Pilar de la Horadada
- I2, Torrevieja to Alicante
- I5, Torrevieja to Crevillente
- I8, Guardamar to Hospital de Torrevieja

Discovery pages:

- https://alibus.es/lines/vegabaja/linea-i1.html
- https://alibus.es/lines/vegabaja/linea-i2.html
- https://alibus.es/lines/vegabaja/linea-i5.html
- https://alibus.es/lines/vegabaja/linea-i8.html

Costa Azul's current L02 diagram confirms Pinomar and La Rosa on the
Pilar de la Horadada, Torrevieja, Alicante corridor:

- https://costazul.net/wp-content/uploads/2026/06/L02.pdf

Costa Azul's current L39 diagram confirms Pinomar and La Rosa on the
Torrevieja, Elche corridor:

- https://costazul.net/wp-content/uploads/2026/06/L39.pdf

The current source set does not yet prove that El Raso, Campico, El Edén,
Los Estaños, or Pórtico Mediterráneo have a second route. Nearby CV-895 stops
must be checked by coordinates before concluding that route 2 is their only
service.

## Municipal route 1

Official diagram:

- https://costazul.net/wp-content/uploads/2026/02/L01_v6-Guardamar.pdf
- https://www.guardamardelsegura.es/wp-content/uploads/2026/04/L01_v6-Guardamar.pdf

The route connects Puerto Deportivo, the town center, the bus-station area,
the beach corridor, Hotel Playas de Guardamar, and Campomar. Selected starred
departures pass Los Secanos and the cemetery.

Important official addresses include:

- Puerto Deportivo: stop 882, `C/ Juan García, 82`
- Campomar: stop 867, `C/ Austria, s/n`
- Estación de Autobuses: `C/ Molivent, s/n`
- east side of the Pintor Sorolla corridor: stop 875,
  `C/ Pintor Sorolla, 2`

No second route has yet been confirmed for Puerto Deportivo, Campomar, or
Hotel Playas de Guardamar.

### Shared central transport area

The bus-station area contains separate stop poles. AliBus currently shows:

- route 1 stop code 856 at approximately `38.0878, -0.655511`
- route 2 stop code 815 about 42 meters away
- interurban `Guardamar` stop code 0020 about 81 meters away at approximately
  `38.088493, -0.6557815`

The interurban stop view currently lists I1, I2, I5, I8, and I16. These labels
are useful for discovery but must be reconciled with operator route names.

Discovery page:

- https://alibus.es/paradas/vegabaja/0020-guardamar/

Current Costa Azul diagrams independently confirm services at
`C/ Molivent, s/n`, including:

- L02, Pilar de la Horadada, Torrevieja, Alicante
- L07, Torrevieja, Universidad de Alicante
- L39, Torrevieja, Elche

Operator index and diagrams:

- https://costazul.net/lineas-interurbanas/
- https://costazul.net/wp-content/uploads/2026/06/L02.pdf
- https://costazul.net/wp-content/uploads/2026/06/L07.pdf
- https://costazul.net/wp-content/uploads/2026/06/L39.pdf

Bus Sigüenza services use the Guardamar bus-station area as well, but their
current stop and schedule mapping was not available during this check and must
be added before the transport guide is complete.

### Pintor Sorolla overlap

Costa Azul route L07 uses:

- `C/ Pintor Sorolla, 2` toward Universidad de Alicante
- `C/ Pintor Sorolla, 1` toward Torrevieja

The route 1 diagram includes `C/ Pintor Sorolla, 2`, and the route 2 diagram
includes nearby Pintor Sorolla stops. The final guide must verify the exact
pole and direction on a map before presenting this as a shared stop.

## Preliminary presentation model

For each recognizable place, store:

- place name
- all confirmed route identifiers and destinations
- exact stop point for each direction
- Google Maps link based on verified coordinates when possible
- source URL and date checked
- confidence state: confirmed, needs map check, or discovery only

The public copy must omit discovery-only routes and must never collapse nearby
stop poles into one map point merely because they share the bus-station name.

## Open checks

- Reconcile AliBus I1, I2, I5, I8, and I16 labels with current Costa Azul
  operator route numbers and schedules.
- Audit every route 2 area against nearby interurban stops, especially CV-895.
- Verify exact direction and coordinates for both El Raso stops.
- Verify exact coordinates for Puerto Deportivo, Campomar, Hotel Playas de
  Guardamar, and the beach stops on route 1.
- Confirm whether any current interurban route serves Playa La Roqueta,
  Campomar, the cemetery, or the port.
- Add current Bus Sigüenza services and exact Guardamar stop points.
- Resolve the difference between the current I8 discovery view, which ends at
  Hospital de Torrevieja, and the broader Generalitat concession itinerary.

## Presentation decision recorded on 2026-08-14

The reviewed public leaf-message format omits both a visible `Проверено` line
and a standalone `Официальное расписание` link. A route whose official search
depends on the travel date may instead end with the compact functional link
`Проверьте актуальное расписание`.

Stop names should be clickable without adding a map-pin icon to every row.
Airport endpoints must link to the terminal bus area. For La Rosa, Pinomar,
and La Mata, the two travel directions may use different physical stops on
opposite sides of the road; exact direction-specific coordinates remain a
publication prerequisite. A general Google Maps search is useful during
review but is not evidence of an exact boarding point.

Only an image file published by the operator is eligible as timetable media.
Do not attach a PDF or publish a locally rendered picture of a PDF page.

The Bus Sigüenza CE-714 airport service is a daily year-round route, not a
summer-only service. A later direct audit of the operator's date-specific
results found three outbound journeys on every sampled date, four return
journeys on sampled July-August dates, and an additional 10:00 return journey
on sampled September-February dates. These observations supersede the earlier
frequency summary but still do not establish an official calendar rule. ADR
0043 therefore updates the pinned message from the actual date-specific result
instead of treating one season's timetable as permanent. See
`research/2026-08-14-bus-siguenza-airport.md`.

## Remaining interurban leaf facts

### South coast corridor

Current operator route L02 directly connects Guardamar with La Mata,
Torrevieja, Orihuela Costa, and Pilar de la Horadada. The operator stop diagram
also lists Pinomar and La Rosa between Guardamar and La Mata, followed by
Torrevieja, Playa Flamenca, Zenia Boulevard, Campoamor, Mil Palmeras, and
Pilar de la Horadada. Public copy should use the date-specific Costa Azul /
Avanza planner rather than reproduce a large seasonal timetable.

### Vega Baja inland corridor

Current Bus Sigüenza CE-714 line 1 directly connects Guardamar with Daya Vieja,
Rojales, Formentera del Segura, Las Heredades, Daya Nueva, Almoradí, Hospital
Vega Baja, Benejúzar, Jacarilla, Bigastro, and Orihuela. Generalitat states
that the route runs throughout the week, with different minimum frequencies
for weekdays, Saturdays, Sundays, holidays, winter, and summer. Public copy
should therefore link the date-specific Bus Sigüenza search.

### Universidad de Alicante

Current Costa Azul route L07 lists Guardamar stops at `C/ Pintor Sorolla, 2`
toward Universidad de Alicante and `C/ Pintor Sorolla, 1` in the return
direction, plus `C/ Molivent, s/n` in both directions. The Universidad de
Alicante transport page states that the ADEUGT service operates during the
teaching period and requires ADEUGT membership. These conditions belong in
the leaf message; `по учебным дням` alone is not sufficient.

### Direction-specific hospital-route map points

The daily Generalitat GTFS downloaded on 2026-08-14 supplies the following
official stop coordinates:

- Alicante-Elche terminal bus area: `38.288404274, -0.552487159`
- Guardamar bus station: `38.0877707496, -0.6560185196`
- La Rosa descending, toward Torrevieja: `38.0583071959, -0.6569832033`
- La Rosa ascending, toward Guardamar: `38.0560738544, -0.6568971718`
- Pinomar: `38.034828419, -0.6600459049`
- La Mata descending, toward Torrevieja: `38.0241372606, -0.6570898059`
- La Mata ascending, toward Guardamar: `38.0262439991, -0.655954`
- Hospital Torrevieja: `37.9643925369, -0.7172232255`

The two directions use separate La Rosa and La Mata points. The current feed
publishes one Pinomar point, so both directions link that same official point
instead of inventing a second platform.
