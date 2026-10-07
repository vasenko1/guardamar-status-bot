# ESIOS next-day PVPC publication

Checked: 2026-07-31

## Official findings

- Red Eléctrica says next-day hourly PVPC prices are updated every day around
  20:15: <https://www.ree.es/es/sala-de-prensa/notas-de-prensa/2014/03/red-electrica-empieza-publicar-los-nuevos-precios-horarios-de-la-electricidad>
- Its consumer guide states 20:20 for publication of the following day's
  hourly prices: <https://www.ree.es/sites/default/files/11_PUBLICACIONES/Documentos/03_Consumidor_Activo_DIGITAL.pdf>
- The current ESIOS API documents personal-token authentication and indicator
  date filtering: <https://api.esios.ree.es/doc/index.html>
- The current PVPC page describes the 2.0TD active-energy term and its official
  green/yellow/orange thresholds: <https://www.esios.ree.es/es/pvpc/>

These statements describe an approximate publication target, not a guaranteed
API availability SLA. The application therefore starts at 20:30 and makes
independent recovery attempts at 20:35, 20:45, 21:00 and 21:20.


## 2026-10-07 incident follow-up

Production received 24 numeric zeros from ESIOS indicator 1001 for
2026-10-08. That was a complete-looking payload, so the historical validator
accepted and published it. The bot now rejects an all-zero day as provisional.

Red Eléctrica also exposes the same official PVPC series through its public
REData API without a personal token:

`https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real`

For Península the request uses hourly truncation and geo ID 8741. The JSON
response exposes the PVPC series as `included[].id == "1001"`, labelled
`PVPC (€/MWh)`, with hourly values under `attributes.values`.

The application keeps token-authenticated ESIOS as the primary source. When
that source fails with a retryable data/transport error (including an
all-zero, incomplete or malformed day), it makes one bounded request to the
official REData endpoint. The fallback is accepted only if it independently
passes the same safety invariants: exact target date, 24 ordered local hours,
finite prices in range and not an all-zero day. Snapshot metadata records
whether the accepted data came from ESIOS or REData.

References:
- REData endpoint family: <https://www.ree.es/es/datos/apidatos>
- ESIOS indicator 1001 describes the active-energy PVPC billing term and
  publishes D+1 daily around 20:20:
  <https://www.esios.ree.es/es/analisis/1001>
