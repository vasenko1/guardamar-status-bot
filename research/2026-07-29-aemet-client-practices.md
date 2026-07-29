# AEMET OpenData client practices checked on 2026-07-29

Primary references:

- AEMET OpenData FAQ v1.4, 2025-07-28:
  <https://opendata.aemet.es/centrodedescargas/docs/FAQs130917.pdf>
- AEMET OpenData Swagger:
  <https://opendata.aemet.es/dist/>
- AEMET municipal forecast notes:
  <https://www.aemet.es/es/eltiempo/prediccion/municipios/guardamar-del-segura-id03076>
- RFC 6585, HTTP 429:
  <https://www.rfc-editor.org/rfc/rfc6585.html>

Verified implications:

- A product request is two-step: `estado`, `datos`, and `metadatos` arrive
  first; `datos` is a temporary URL valid for about five minutes.
- If that URL expires, repeat the original API request rather than retaining
  or repairing the URL.
- AEMET documents `200`, invalid-key `401`, no-data `404`, and throughput
  `429`, plus a limit of 40 connections per minute per user and a global
  service limit.
- `429` may include `Retry-After`; a client must not retry before a usable
  value and should stop when it exceeds its local runtime budget.
- Municipal forecast periods of six hours or more use UTC. Convert them to
  `Europe/Madrid` before rendering.
- Sequential requests, bounded response sizes and timeouts, no temporary URL
  cache, and transient-only retries fit this project's one-shot Termux model.
