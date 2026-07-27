# AEMET and SafeBeach Data Inventory

## Question

Which useful Guardamar beach and weather fields do AEMET and SafeBeach
provide, and where can one source safely act as a fallback for the other?

## Sources checked

- [AEMET OpenData API specification](https://opendata.aemet.es/AEMET_OpenData_specification.json),
  accessed 2026-07-27
- [AEMET beach forecast for Centro / La Roqueta](https://www.aemet.es/es/eltiempo/prediccion/playas/centro-la-roqueta-0307605),
  beach code `0307605`, accessed 2026-07-27
- [SafeBeach Guardamar public page](https://info.safebeach.es/guardamar-del-segura),
  accessed 2026-07-27

Both providers are official for the intended use: AEMET is Spain's state
meteorological authority, while the Guardamar municipality links to the
SafeBeach page used by its beach service.

## AEMET data

### Guardamar municipal forecast `03076`

- daily minimum and maximum air temperature;
- forecast wind direction and speed by period;
- sky, precipitation, humidity, and other municipal forecast fields not
  currently needed by the digest.

### Rojales observation station `7261X`

- observation timestamp;
- measured air temperature;
- measured wind direction and speed;
- other conventional observation fields not currently needed.

This is the nearest AEMET observation station listed for Guardamar, not a
measurement made on the beach.

### CAP warnings for area `77`

- event and severity;
- validity start and end;
- affected geographic areas;
- descriptive warning fields.

The bot filters these records to `Litoral sur de Alicante`.

### Beach forecast `0307605`: Centro / La Roqueta

- forecast water temperature;
- forecast wave conditions;
- forecast wind category;
- sky condition;
- maximum air temperature;
- apparent-temperature category;
- maximum UV index;
- applicable warnings.

This product is a forecast. Its water temperature is suitable as a fallback
when SafeBeach has no current water temperature, but it must not be presented
as a live measurement.

## SafeBeach data

The public page currently embeds a structured `window.SB_MARKERS` array.
Relevant per-beach fields observed include:

- `beachName`;
- `hasActividad`;
- `serviceEnded`;
- `textoBandera`;
- `colorBandera`;
- `waterTemp`.

The page lists six Guardamar beaches, including
`Platja Centre / Babilònia`. SafeBeach supplies the operational flag chosen by
the beach service and may supply a current water temperature while the service
is active.

At 02:27 Europe/Madrid on 2026-07-27, all six records had
`hasActividad: false`, an empty flag label, grey `#CCCCCC`, and
`waterTemp: "No disponible"`. This confirms that an available webpage does not
necessarily contain an active current beach status.

The embedded schema is public but undocumented and may change. Parsing must
remain bounded, fixture-tested, and optional.

## Safe fallback matrix

| Digest value | Primary | Safe fallback | Rule |
| --- | --- | --- | --- |
| Beach flag | SafeBeach | None | Never infer a flag from weather, wind, waves, or warnings |
| Water temperature | Active SafeBeach value | AEMET beach forecast `0307605` | Distinguish internally between current status and forecast |
| Wave conditions | AEMET beach forecast | AEMET coastal forecast if later approved | Do not translate waves into a flag |
| Current air temperature and wind | Fresh Rojales observation | Guardamar AEMET forecast | Do not label forecast data as a current observation |
| Weather warnings | AEMET CAP | None | Unavailable warning data is unknown, not “no warnings” |

## Recommendation

For a later slice, add the AEMET beach forecast only as a water-temperature
fallback for Centro / La Roqueta. Keep the flag exclusively from an active
SafeBeach record for `Platja Centre / Babilònia`. Do not add wave or UV rows
unless real usage demonstrates that they improve the short digest.

No product decision or implementation change is made by this research note.
