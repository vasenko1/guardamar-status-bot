# Municipal Wi-Fi source verification — 2026-09-16

## Scope

Verify the official source used for the Guardamar municipal Wi-Fi guide card and identify the cheapest reliable change signal suitable for the Termux runtime.

## Official sources checked

Municipal landing page:

`https://www.guardamardelsegura.es/wifis-municipales/`

Asset linked by that landing page on 2026-09-16:

`https://www.guardamardelsegura.es/wp-content/uploads/2021/06/PLANO-WIFIS-GUARDAMAR-PU%CC%81BLICAS.pdf`

A separate 2023 JPG upload with the same map facts is also reachable, but the current `Wifis Públicas` landing page does not use it as its linked source. The source watch therefore uses the 2021 PDF URL as the reviewed linked baseline. This distinction was confirmed by a live GitHub Actions smoke check against the page rather than inferred from upload dates.

## Current reviewed facts

The linked municipal map shows seven access points:

1. Escola de Música, C/ Mercat, 2 — `WiFi4EU`, no password.
2. Casa de Cultura, C/ Colón, 60 — `WiFi4EU`, no password.
3. Avda. Los Pinos — `WiFi4EU`, no password.
4. Plaza de la Constitución — `vegafibra_gratis` / `vegafibra`.
5. Paseo Marítimo · Avda. de Europa — `vegafibra_gratis` / `vegafibra`.
6. Sala de Estudios 24/365, C/ Mayor, 69 — `wifi_1EO9C` / `vegafibra`.
7. Biblioteca Pública, C/ San Jaime, 5 — `wifibiblioteca` / `biblimar`, `biblioteca infantil` / `menjallibres`, and `vicenteramos` / `menjallibres`.

The WiFi4EU access points use the common `WiFi4EU` SSID and captive-portal confirmation rather than a local password.

## Change-signal conclusion

The useful signal is the asset currently linked by the municipal landing page, not which upload has the newest-looking path and not whether a separately known upload remains reachable. One bounded landing-page GET and exact linked-asset comparison is sufficient for the first implementation.

Failures to fetch or extract exactly one candidate are not evidence of a factual change. They must preserve the reviewed baseline and produce no public update.

## Accepted blind spot

This first implementation does not detect a municipality replacing bytes at exactly the same asset URL. No evidence observed during this review justifies daily image hashing. If same-URL replacement is later observed, add the smallest bounded content fingerprint then.
