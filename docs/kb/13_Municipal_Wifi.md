# Municipal Wi-Fi guide

## Purpose

The linked city guide exposes one durable `📶 Бесплатный Wi-Fi` card directly from the `📌 Полезное о Гуардамаре` root. Wi-Fi is not classified as a place. It is static resident-facing information; it is not a separate bot, scheduled publisher, or automatically rewritten source feed.

The architecture decision is recorded in `adr/0068-municipal-wifi-guide-source-watch.md`. Dated source verification belongs in `research/2026-09-16-municipal-wifi-source.md`.

## Approved public content

The card contains seven municipal Wi-Fi locations from the reviewed official Ayuntamiento Wi-Fi map:

- Escola de Música, C/ Mercat, 2 — `WiFi4EU`, no password;
- Casa de Cultura, C/ Colón, 60 — `WiFi4EU`, no password;
- Avda. Los Pinos — `WiFi4EU`, no password;
- Plaza de la Constitución — `vegafibra_gratis` / `vegafibra`;
- Paseo Marítimo · Avda. de Europa — `vegafibra_gratis` / `vegafibra`;
- Sala de Estudios 24/365, C/ Mayor, 69 — `wifi_1EO9C` / `vegafibra`;
- Biblioteca Pública, C/ San Jaime, 5 — `wifibiblioteca` / `biblimar`, `biblioteca infantil` / `menjallibres`, and `vicenteramos` / `menjallibres`.

For WiFi4EU, the user confirms the captive-portal connection; the public card does not require or imply local documentation or registration.

Place names are map links. The card returns to `Полезное о Гуардамаре` and uses the standard public-message footer. The pinned root contains Wi-Fi as one direct item alongside the existing guide sections.

## Source policy

The official landing page is:

`https://www.guardamardelsegura.es/wifis-municipales/`

The currently reviewed asset URL is held explicitly in `telegrambot.guide` as the human-reviewed baseline. The linked asset URL, not the continued existence of an older file, is the source-change signal.

## Minimal source watch

Reuse the existing daily `telegrambot.guide sync` run. When `TELEGRAM_ALLOWED_USER_IDS` is configured, the sync performs one bounded GET of the municipal Wi-Fi landing page and extracts exactly one linked Wi-Fi asset.

- current asset equals the reviewed asset: do nothing;
- source request or parsing is unavailable/ambiguous: log a warning and preserve state;
- asset URL differs from the reviewed asset: send one private operator alert and do not change public Wi-Fi facts automatically;
- after one successful operator delivery, store only `wifi_last_alerted_asset_url` in the existing `state/guide.json` to deduplicate that observed version;
- if delivery fails, do not store the dedupe value; the next normal guide sync retries without a separate retry subsystem.

The parser preserves query parameters and ignores only URL fragments. A new linked asset may live on another HTTP(S) host; that is still a change worth reviewing.

## Deliberate limits

Do not add SHA-256 polling, ETag/Last-Modified state, OCR, image parsing, BeautifulSoup, Selenium, WordPress API logic, a Wi-Fi daemon, a new cron row, another state file, automatic SSID/password updates, or automatic public change notices.

The accepted blind spot is replacement of asset contents under the exact same URL. Add content hashing only after evidence shows the municipality actually uses same-URL replacements.
