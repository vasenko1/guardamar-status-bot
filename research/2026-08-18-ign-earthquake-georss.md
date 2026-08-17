# IGN public earthquake feed investigation

Date checked: 2026-08-18

## Result

The suitable official machine-readable source is:

- `https://www.ign.es/ign/RssTools/sismologia.xml`

The endpoint returned a small RSS 2.0 XML document with GeoRSS latitude and
longitude fields. Each item included an IGN event identifier, magnitude, UTC
date and time, source place wording, and decimal coordinates. The coordinates
also appeared in the Spanish description, allowing deterministic
cross-validation.

No separate public REST API with a documented stability or versioning contract
was found for the required latest-earthquake query. The public GeoRSS is
therefore treated as the supported publishing interface, with strict bounds
and fail-closed schema handling rather than assumptions about private IGN web
requests.

## Map investigation

IGN event pages use interactive Leaflet maps and IGN tile services. Some
intensity products may appear later, but no stable official static image was
found that is guaranteed to exist immediately for every new event. The bot
therefore does not fetch tiles or create a screenshot. It links the rendered
epicenter label to the event's exact decimal coordinates in Google Maps.
Google Maps is only a display destination; no event fact is collected from it.

For the reviewed example coordinates `38.0625, -0.6789`, the great-circle
calculation from the project's Guardamar reference `38.0896, -0.6553` is about
3.65 km toward the southwest. Google Maps may display the same decimal point as
degrees, minutes and seconds; that conversion does not change the location.

## Runtime implications

One hourly read is about 24 small XML requests per day. The implementation
uses a ten-second request timeout, 256 KiB response cap, 128-item parse cap, no
internal retry, no raw cache, and bounded identifier-only state. Minute `:55`
does not overlap the currently documented cron entries, including the 04:00
deployment.
