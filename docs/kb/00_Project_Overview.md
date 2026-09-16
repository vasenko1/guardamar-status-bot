# Project Overview

## Summary

TelegramBot is a small city-information bot designed to run in Termux on a
low-powered Android device. Its main feature is the **Morning Digest**: one
short Telegram message that helps a user understand the day at a glance.

The digest may cover:

- weather;
- sea conditions;
- beach flag status;
- official warnings;
- important municipal updates;
- official national, regional, and Guardamar holiday days off;
- events relevant today, including narrowly validated late municipal
  announcements.

Sections are included only when current, useful information is available. The
bot does not need to fill every section every day.

## Project goals

- Deliver a concise and dependable morning status.
- Use official, authoritative sources only.
- Make important information easy to notice.
- Continue to provide partial value when one source is unavailable.
- Run reliably with little memory, CPU, storage, and network traffic.
- Remain simple enough for one operator to understand and recover.

## Scope

### Morning Digest

The first and primary feature. It collects a limited set of official city data,
keeps only information relevant to the day, and sends one compact message.

### Next-day electricity prices

The approved second feature publishes one evening PVPC price table for the
next local day from ESIOS / Red Eléctrica. It is independent of the Morning
Digest and runs as another short-lived Termux process.

### Linked pinned city guide

One recoverable Telegram graph connects a compact pinned root to cameras,
transport, durable places, and recurring activities. The current place/activity
slice includes `Места → Polideportivo Municipal →` the indoor and outdoor
municipal pools, `Места → Centro Social Juvenil`, plus
`Занятия и секции → Плавание` with direct cross-links between the activity and
both pool cards.

Most guide content is static. The existing 05:00 transport sync keeps its
transport media current and also reconciles the shared message graph. A separate
short 16:30 `sync-guide` invocation reads only a small normalized public
SimplyBook catalogue baseline for swimming, reconciles the same graph, and
publishes the deterministic June/September pool-season notice when due. It does
not infer registration availability from stale catalogue entries.

### Local earthquake notices

One short hourly Termux invocation checks the official IGN GeoRSS feed. It
publishes only a newly observed event of magnitude 2.7 or greater whose
epicenter is no farther than 10 km from Guardamar. The monitor is a quiet
informational feature, not an emergency-warning service.

## Out of scope

- General news aggregation
- Continuous or real-time emergency monitoring
- Replacing official emergency or municipal channels
- Conversational AI or generated advice
- General AI summarization, classification, or ranking outside the approved
  Policía Local, market-exception, and municipal-poster workflows
- User-generated or unverified information
- Web dashboards, webhooks, microservices, or server infrastructure
- Continuous OCR, image analysis, or other heavy on-device processing

## Intended users

- Residents or visitors who want a quick morning city update
- The operator maintaining the bot in Termux
- Contributors and coding agents working within the documented constraints

## Success criteria

The project is successful when the digest is:

- brief enough to scan in seconds;
- accurate and traceable to official sources;
- useful without requiring follow-up reading on routine days;
- quiet when nothing important can be verified;
- reliable on the target Android device.

## Current phase

The MVP first publishes one immutable short message at 07:30. During the
SafeBeach season, short external invocations check for complete current beach
data every five minutes from 10:10 through 10:40. Before the final attempt,
completeness requires current flags for all six known Guardamar zones. At
10:40, any non-empty verified Guardamar beach set is eligible. The first
usable beach or Mayor fact creates a separate daily beach root; later verified
coverage enriches that same root without changing the Morning Digest.
There is no resident scheduler, sleeping retry process, background collector,
or cache synchronization. A separate optional
operator listener may use one idle Telegram long poll solely for allowlisted
private `/preview`; it never publishes or changes publication state.

Bounded one-shot checks may publish a reply only when a beach flag, explicit
jellyfish status, AEMET warning, remaining-day CAMS meaning, or same-day
Meteosalud risk has actually changed. Beach replies use the beach root; the
other updates use the immutable Morning Digest. They remain silent on unchanged,
stale, or unavailable source data.
An independent hourly one-shot process may publish a compact local earthquake
notice from IGN. It retains only a bounded identifier set for deduplication and
the latest normalized parameters needed for revisions and series editing. It
does not keep a raw feed or a resident process.
