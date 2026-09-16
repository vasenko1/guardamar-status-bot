# ADR 0068: Municipal Wi-Fi guide and source watch

## Status

Accepted — 2026-09-16

## Context

Guardamar publishes a municipal Wi-Fi map with seven durable public access points, SSIDs and passwords. These facts are useful resident-facing reference information but change too rarely to justify another scheduled subsystem. The existing linked city guide already provides durable place information and the existing 16:30 `sync-guide` one-shot has a small atomic `state/guide.json`, a runtime lock, bounded HTTP transport and private operator configuration.

The municipality may publish a replacement Wi-Fi map while an older upload remains reachable. Continued availability of the old file therefore does not prove that the published facts are still current.

## Decision

Add one static `📶 Бесплатный Wi-Fi` card as a direct entry in the compact `📌 Полезное о Гуардамаре` root. Do not classify Wi-Fi as a place. The card contains only the seven facts verified from the current official municipal map and uses the established guide footer and backlink conventions.

Reuse the existing daily `telegrambot.guide sync` invocation for one lightweight source watch when `TELEGRAM_ALLOWED_USER_IDS` is configured:

1. perform one bounded HTTPS GET of the official `/wifis-municipales/` landing page;
2. extract exactly one linked municipal Wi-Fi asset and resolve relative links with `urljoin`;
3. compare that asset URL with the human-reviewed baseline constant;
4. remain silent when they match;
5. on source, MIME, decoding, missing-link or ambiguous-link failure, preserve state and public content;
6. when the asset changes, send one private operator alert asking for manual review and do not rewrite public Wi-Fi facts automatically;
7. after one confirmed alert delivery, store only `wifi_last_alerted_asset_url` in the existing `state/guide.json` so the same observed version is not reported every day.

A failed or ambiguous Telegram send does not advance the deduplication state. The next ordinary guide sync is the retry path. No separate retry job is added.

## Constraints

Do not add another cron entry, daemon, state file, dependency, browser, WordPress API client, OCR, image parsing, SHA-256 polling, ETag/Last-Modified history, automatic SSID/password extraction or automatic public source-change message.

Content replacement under the exact same asset URL is an accepted blind spot. Add a content hash only if production evidence later shows that the municipality replaces the file in place.

## Consequences

- Residents get one useful static Wi-Fi reference card directly from the pinned root; the root intentionally gains one item.
- The phone pays for one small daily HTML request only when a private operator allowlist exists.
- A new municipal asset becomes a human-review trigger rather than an automatic public fact change.
- Source failures cannot erase or silently mutate the reviewed Wi-Fi information.
- The implementation stays inside the existing guide lock, state and scheduling model.

## Rejected alternatives

- New Wi-Fi cron or daemon: unnecessary operational surface for rarely changing data.
- Poll or hash the image every day: more bandwidth and complexity without evidence that same-URL replacement occurs.
- OCR or parse credentials automatically: unnecessary risk for a tiny manually reviewable source.
- Check only whether the 2023 asset still returns HTTP 200: an old upload may remain reachable after the landing page links a newer map.
