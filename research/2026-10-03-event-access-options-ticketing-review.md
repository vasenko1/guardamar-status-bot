# Multi-option registration, reservation and ticket access review

## Status

Research/design review completed 2026-10-03.

No runtime code, state, cron or Telegram behavior is changed by this file.

ADR 0091 records the durable target architecture.

## Why the scope expands beyond registration

Official Guardamar sources repeatedly expose four resident experiences:

- registration;
- place/seat reservation;
- paid ticket sale;
- free invitation/ticket claim.

Examples from official Turismo programming include paid ticket links,
free invitation links, telephone/WhatsApp reservation and walk-in free
admission within the same monthly programme.

The proactive product goal is therefore not "registration monitoring" in the
narrow language sense. It is:

**tell residents when a source-backed way to secure access to an event becomes
available, and keep later availability changes threaded under that event.**

Walk-in events with no advance action remain ordinary event information.

## Source evidence reviewed

### Official Turismo cultural programme

The official April 2026 cultural page demonstrates several access types in one
source:

- cinema with free invitation;
- paid dance/theatre ticket links;
- a children's activity with 20 places and phone/WhatsApp reservation;
- free entry until capacity with no advance action;
- guided tours with paid ticket purchase or registration.

The current September programme similarly includes:

- Casa de Cultura in-person ticket-sale windows;
- free invitations through Agenda Guardamar;
- free walk-in cinema until capacity;
- limited-place workshop registration.

A separate August Turismo article explicitly states that concert tickets are
already on sale and points residents to Agenda Guardamar.

This proves proactive ticket/reservation lifecycle is a real municipal need,
not a speculative abstraction.

### Agenda Guardamar

Current code already:

- discovers official event detail pages;
- parses up to a 45-day event horizon;
- finds multiple occurrence-specific `/entradas/` links on one detail page;
- validates each ticket URL against its exact event date/time;
- materializes each occurrence as an Event with price and ticket URL.

Current loss: the normalized snapshot does not keep the parent detail-page URL
or parent event identity. Multi-option lifecycle therefore cannot yet
reconstruct one event root safely from flattened occurrence rows.

### Municipal session families

Current municipal code already recognizes source-proven session families
through `session_source_key` / `session_group_key`.

This is directly relevant to Escape Room-style cards, but production probes
must confirm durable identity and per-session registration URL behavior before
using it as lifecycle state.

### FACV

Official Guardamar tournament articles demonstrate:

- registration by email;
- registration by WhatsApp;
- one web form;
- capacity-based closure;
- registration prices.

These are several action methods for one registration option, not several
time-slot options.

### Biblioteca

The official Guardamar library publishes a first-party activity-registration
form. Existing adapter infrastructure already retains stable detail URLs and
fetches changed detail pages.

Event-specific reservation evidence still needs a production probe.

### AM Guardamar

The adapter already retains official WordPress post IDs, featured images and
Event access presentation fields. Registration/ticket extraction frequency and
source semantics still need live evidence.

## Best-practice comparison for multiple sessions

Major ticketing systems model timed entry as:

- one event overview;
- multiple dates/time slots;
- slot-specific availability/dashboard state.

This matches the proposed one-root + child-options architecture and is simpler
for residents than several repeated event cards.

The source relationship remains authoritative: do not infer one event family
from fuzzy titles.

## Recommended root-card template

### Several different links

```text
📝 Открыта регистрация

<Название события>
📅 18 октября
📍 <место>

<краткое русское описание>

Регистрация:
• 10:00 — Записаться
• 12:00 — Записаться
• 13:00 — Записаться

Места ограничены
```

Each `Записаться` label is an ordinary HTML link.

### One shared action

```text
🕐 Сеансы: 10:00 · 12:00 · 13:00
📝 Записаться
```

Do not repeat an identical URL three times.

### Ticket sale

```text
🎟 Билеты поступили в продажу

<event card>

• 18:00 — Купить билет
• 20:30 — Купить билет
```

### Free invitation

```text
🎟 Доступны бесплатные приглашения

<event card>

Получить приглашение
```

### Reservation

```text
📌 Открыта бронь мест

<event card>

• 11:00 — Забронировать
• 13:00 — Забронировать
```

Exact emoji/text remains a renderer decision; semantics are the important
contract.

## Follow-up semantics for partial slot changes

If one option fills:

```text
⏰ Сеанс 12:00 — мест больше нет.
На 10:00 и 13:00 запись ещё открыта.
```

If two options change in the same observation, combine them into one reply to
that event root.

If all known options are terminal, render an event-level summary appropriate
to the access kind.

Never say the whole event is full while any known option remains open or an
unresolved option is still unknown.

If a new session is added:

```text
➕ Добавлен сеанс 15:00 — регистрация открыта.
```

Disappearance alone stays silent.

## Why inline keyboards are not the first implementation

Telegram supports URL buttons, but the current bot already sends validated HTML
links in text/photo captions.

Buttons would require:

- new reply-markup plumbing;
- decisions about editing/removing stale buttons when one slot fills;
- additional tests around root edits and delivery recovery.

Text links keep the root self-contained, forwardable and readable with no new
state. Revisit buttons only if actual user feedback justifies them.

## Access-kind mapping

### registration

Use for formal sign-up/inscripción.

Positive current evidence may be a reviewed form, explicit open instruction or
registration contact.

### reservation

Use when the source explicitly asks residents to reserve a place/seat, usually
without a paid ticket.

### ticket

Use for paid tickets and free invitation/ticket claims.

A zero-price ticket action remains `ticket`, with user-facing invitation/free
wording from source evidence.

### excluded walk-in

`Entrada libre hasta completar aforo` with no advance action is not proactive
access lifecycle input.

It remains Morning/Tomorrow/Weekend event information only.

## What "ticket sale appeared" means

Yes: when a source-specific adapter positively proves tickets are currently
obtainable, the next lifecycle run should notify immediately.

However:

- a price alone is insufficient;
- an event saying tickets will be sold later is future-boundary evidence, not
  current-open;
- an occurrence-specific ticket link may count only after the source contract
  is verified to mean current availability;
- sold-out/closed must remain explicit/fail-closed.

This is the same evidence discipline as registration.

## Current architecture reuse

Do not replace the global Event model.

The current renderer already distinguishes:

- ticket price;
- free ticket acquisition;
- ticket URL;
- access note;
- registration URL/contact;
- capacity.

The proactive lifecycle should reuse those source facts but maintain its own
source-owned identity/status/options before global Event merging.

## Required production probes before implementation

### Agenda Guardamar

For representative future events:

- retain detail-page URL/identity;
- inspect one page with several ticketed sessions;
- determine whether occurrence ticket links exist before sales open;
- determine sold-out/closed page behavior;
- inspect image availability;
- measure publication/update timing.

### Municipal/Turismo

For a multi-session registration event:

- verify parent/source identity;
- enumerate session-specific registration URLs;
- test whether each session can change availability independently;
- verify poster/presentation completeness.

For paid/invitation events:

- inspect how sale/invitation actions are represented;
- distinguish future sale window from current sale.

### Library

Probe a current/future reservation activity and first-party detail page for
stable action/capacity evidence.

### AM Guardamar

Probe recent posts with paid/free admission facts and determine whether the
existing normalized extraction reliably retains actionable access.

### FACV

Retain article/detail identity and confirm one option with multiple action
methods.

### Simultaneous volume

Count how many independent event roots and how many options per root would be
eligible in a normal day.

The result determines any future per-run safety cap.

## Implementation boundary

The implementation should generalize the current one-off lifecycle once, not
run a parallel registration engine and ticket engine.

Likely target:

```text
source snapshots
      ↓
source-specific EventAccessRecord projection
      ↓
per-source freshness filter
      ↓
one event root + options
      ↓
rich root / threaded option-event lifecycle replies
```

Course notifications remain separate.

No browser, database, message broker, generic commerce model or continuous
polling is justified.
