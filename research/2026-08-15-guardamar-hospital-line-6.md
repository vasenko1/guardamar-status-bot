# Guardamar to Hospital de Torrevieja, line 6

Checked on 2026-08-15 after the legacy Autobusing journey planner returned
`Estacion cerrada temporalmente` for both directions.

## Current official evidence

- Generalitat Valenciana states that CE-704 has operated since spring 2026.
- Its line 6 is `Guardamar-Hospital de Torrevieja-Pilar de la Horadada`.
- The current concession notice specifies six journeys per direction on
  working Mondays to Fridays and four per direction on Saturdays, Sundays and
  public holidays.
- The signed definitive CV-214 service project publishes one all-year table.
  Guardamar departures are `07:30, 09:00, 11:00, 13:00, 15:00, 17:30` on
  working weekdays and `07:30, 09:00, 13:00, 16:30` on weekends and holidays.
  Hospital departures toward Guardamar are 30 minutes later.

The Generalitat daily GTFS downloaded on 2026-08-15 does not yet list CE-704.
Its own catalog warns that route information may omit the latest changes, so
it cannot currently drive this message safely.

## Product consequence

The pinned message carries the explicit all-year table and links to the current
Generalitat concession notice. The retired generic Autobusing search link is
removed. Do not treat a failure of that old planner as a route suspension.

## Sources

- https://www.gva.es/es/web/arees/infraestructures-i-transports/-/asset_publisher/21dbI2RUgqwC/content/nuevas-concesiones-de-atuob%25C3%259As-en-la-comarca-de-la-vega-baja/20081096?_com_liferay_asset_publisher_web_portlet_AssetPublisherPortlet_INSTANCE_21dbI2RUgqwC_assetEntryId=412097993
- https://estaticos-cdn.prensaiberica.es/epi/public/content/file/original/2025/0827/18/proyecto-definitivo-actualizado-junio-2024-cv-214-torrevieja-alacant-firmado-pdf.pdf
- https://dadesobertes.gva.es/dataset/tra-hyr-atmv-horaris-i-rutes
- https://gvinterbus.gva.es/estatico/gtfs.zip
