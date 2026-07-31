# AEMET future-warning observation — 2026-07-31

The official latest CAP package for Comunitat Valenciana area `77` contained
a Spanish `Moderate` warning for `Litoral sur de Alicante` before its onset:

- event: `Aviso de tormentas de nivel amarillo`;
- effective: 2026-07-31 11:07:15 Europe/Madrid;
- onset: 2026-08-01 16:00 Europe/Madrid;
- expiry: 2026-08-01 21:59:59 Europe/Madrid.
- probability: `40%-70%`;
- description: possible very strong wind gusts, hail, and locally heavy
  showers.

The previous product rule omitted any warning whose onset local date was after
the collection date. The CAP item was therefore valid and published but absent
from preview. The product now retains already published future hazardous
warnings and renders their official validity interval. `Minor` green records
remain excluded because AEMET defines them as no-warning level. The supplied
package contained 26 CAP documents and 20 zone records: ten Spanish plus ten
English duplicates. Nine pairs were `Minor`; one Spanish/English pair was the
yellow thunderstorm warning, so the correct user-facing hazardous count was
one.
