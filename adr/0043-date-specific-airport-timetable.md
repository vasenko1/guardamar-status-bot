# 0043: Date-specific airport timetable and verified fare

- Status: Accepted
- Date: 2026-08-14
- Extends ADRs 0041 and 0042

## Context

The Bus Sigüenza airport planner publishes structured date-specific departures,
exact endpoint coordinates and a current official Generalitat tariff PDF. A
cross-season sample disproves the existing simplified seasonal copy: an extra
10:00 airport departure appears on sampled September-February dates but not on
sampled July-August dates. The operator does not publish a safe calendar rule
that the bot can reproduce.

## Decision

Extend the existing 05:00 one-shot transport sync. It makes one bounded POST
for the current Madrid date and validates exactly two Guardamar-airport
directions, ordered unique times and one plausible official coordinate per
direction. The existing airport text message is edited in place and labels the
exact service date. A link remains for checking another date.

The fare link is optional and independent. Its PDF uses conditional requests.
A changed document must download twice identically, pass bounded Poppler
metadata and text extraction, and match the official authority, concession,
line, signature, effective date, stop order and tariff-row structure. Only the
standard Guardamar-airport fare is shown. A future tariff is withheld before
its effective date; an unknown changed layout removes the price without hiding
the timetable.

Bus Sigüenza currently serves a Let's Encrypt leaf certificate with an
unrelated legacy intermediate chain. Default verification correctly rejects
it on Termux. Only for missing-issuer verification errors on the exact operator
host, read the leaf AIA without trusting application data, require one
`*.i.lencr.org` issuer URL with no extra path or parameters, upgrade it to
HTTPS, download a bounded DER intermediate through the normal system trust
store, and retry with hostname and certificate verification still required.
No other TLS error may enter this recovery path, and no certificate is stored.

Store one small strict atomic normalized snapshot, with one previous
generation, but no raw HTML or PDF. It supports exact-date labeling during a
source outage and recovery of an accidentally deleted bot-authored airport
message. The message graph and uncertain-delivery rules remain owned by the
pinned-guide state.

## Consequences

- Normal daily cost is one small POST and normally one conditional PDF `304`.
- While the operator's chain remains incomplete, one bounded Let's Encrypt
  intermediate fetch is shared in memory by the timetable and fare requests.
- `pdfinfo` and `pdftotext` run only after a stable changed fare PDF; both are
  already supplied by the accepted Termux Poppler dependency.
- No browser, image generation, OCR, AI, new cron row or resident process is
  added.
- A source outage leaves a visibly dated accepted message instead of claiming
  that stale departures are current.
- A deleted airport message is recreated from a validated current or cached
  normalized snapshot and the transport navigator is relinked in the same run.

## Alternatives considered

- Publish one permanent timetable: rejected because official results change
  with the requested date.
- Infer summer and winter boundaries: rejected because the sampled behavior
  is evidence of variation, not an official calendar rule.
- Publish a generated timetable image: rejected because the compact times fit
  naturally in text and the accepted guide policy reserves media for original
  operator images.
- Parse the fare PDF every day: rejected as unnecessary CPU work on the phone.
