# 0090: Thread one-off registration updates under one event root

- Status: Accepted
- Date: 2026-10-03
- Implementation: v2 text-root rollout deployed; optional photo-root refinement pending validation
- State layout: refined by ADR 0092

## Context

ADR 0089 introduced a crash-safe one-off registration lifecycle. Its deployed
v1 renderer may combine notices for multiple records into one Telegram message
and stores audience knowledge separately from Telegram message identity.

The next product requirement is stronger:

- the first proactive registration publication for one event should be a rich,
  Russian event card, preferably with the event-specific official poster;
- later deadline, full, closed, correction and reopen notices should be replies
  to that original event card so a resident can jump back to the detailed
  context;
- multiple independent events must therefore never share one registration
  root message.

Telegram Bot API supports replies through `reply_parameters`. The existing
shared `send_message()` wrapper already sends strict replies with
`allow_sending_without_reply=false`. The missing architecture is per-record
root identity and crash-safe root delivery.

## Decision

### One event owns one Telegram root

Each accepted one-off registration `record_id` may own at most one current
Telegram root message.

The first publishable registration notice for that record establishes the
root. This is not restricted to first-seen current `open`; it may also be an
explicit future-opening notice when that is the first useful participation
information.

The root should be one self-contained rich event card:

- event-specific official image when uniquely attributable and safe to send;
- Russian title and compact translated event description;
- event date/time/place and other material participation facts;
- current registration action/contact when already open;
- explicit registration boundary/capacity conditions when known.

If no safe unique image exists, the same root is a text card. Media availability
does not affect lifecycle truth.

### Every later lifecycle publication replies to that root

After the root exists, later notices for the same `record_id` use a strict
Telegram reply to the stored root `message_id`.

This includes, when applicable:

- registration becomes currently open after a previously announced future
  opening;
- first discovered deadline or later deadline revision;
- tomorrow/today deadline reminders;
- full;
- closed;
- reopened;
- material event-date corrections.

Replies remain compact. The poster is not repeated merely because state
changed.

### Do not batch different records into one lifecycle message

Cross-record registration batching is incompatible with one-root-per-event
threading and is therefore retired for the multi-source/threaded lifecycle.

Planning and delivery operate per `record_id`. A single invocation may
process independent publications sequentially, but each send has its own
crash-safe reservation and commit.

The implementation must **not** reuse the v1 batch-state rule that advances the
baseline for every publishable record when only one event root was actually
sent. Process records deterministically one at a time:

1. a record with no publication may commit its silent semantic baseline;
2. a publishable record is reserved, sent and committed before moving on;
3. an unsent publishable record keeps its prior baseline and therefore remains
   eligible for the recovery/next invocation.

This avoids losing a first-open/root publication merely because another event
was sent earlier in the same run.

No queue, worker, database or long-lived process is introduced.

### Root publication absorbs same-run facts

When the first root is created, it should include every material registration
fact already known for that record.

For example, first discovery of an already-open registration whose deadline is
tomorrow produces one rich root card that includes that deadline. It must not
immediately generate a second deadline reply in the same run.

Triggers represented in the root are acknowledged atomically with successful
root delivery.

### Persist lifecycle state around the event root

ADR 0092 refines the pending state shape.

Do not extend ADR 0089 as separate global baseline/announced/root/trigger
collections. The new bounded state stores one entry per lifecycle
`record_id`, containing:

- semantic event/option state;
- `audience_known`;
- optional Telegram root metadata;
- record-local sent trigger history.

Telegram root metadata remains presentation/delivery state and must not
participate in source-semantic comparisons.

When an event ages out of lifecycle retention, remove that one event entry so
its semantic state, audience flag, root and triggers are pruned together.

### Preserve legacy audience knowledge during migration

ADR 0089's `announced_record_ids` remains useful only as migration input.

A legacy record that was already shown to residents becomes
`records[record_id].audience_known=true`, even when no recoverable per-event
Telegram root exists.

Such a record must not be rewritten as "never announced" merely because
threading metadata is absent.

### Migrate state v1 fail-safe

The deployed v1 state is migrated once into ADR 0092's event-centric schema
without deleting baseline, last-explicit-status, audience or trigger history.

Existing v1 records have no per-event root metadata. Migration itself creates no
Telegram publication and no Telegram root ID may be invented.

Normal runtime supports only the new state version after successful migration;
do not keep a permanent dual-schema compatibility path.

### Crash safety for new roots

Before a new root send, persist one uncertain reservation exactly as in ADR
0089.

On a confirmed successful text send, store the returned Telegram message ID.
On a confirmed successful remote-photo send, store the returned Telegram
message ID; the returned file ID may be retained only if useful for future
media operations.

A deterministic failure that proves no message was created clears the
reservation for normal recomputation.

An ambiguous root send remains blocked. Because a later reply requires the
actual Telegram root ID, operator resolution of an ambiguous root send as
"sent" must require the verified Telegram message ID. Do not commit a
root-as-sent state without that ID.

Ambiguous follow-up replies do not require storing their own Telegram message
ID and retain the existing sent/unsent operator resolution semantics.

### Strict reply target and missing-root behavior

Normal follow-ups use strict reply semantics. Telegram must not silently send
a supposedly threaded notice as a standalone message if the stored root no
longer exists.

If Telegram deterministically reports that the root reply target is gone, the
runtime may create one replacement self-contained event root from current
accepted presentation facts and use that new root for later updates. This
recovery must be an explicit tested path; it must not be triggered by timeout
or other ambiguous delivery.

Until that recovery path is implemented, missing-root delivery fails closed
rather than silently degrading to an unthreaded update.

### Future-opening roots

If an explicit future registration boundary is the first proactive notice, the
rich card becomes the root even though registration is not open yet.

When the source later positively reaches current `open`, a concise reply is
**required** when the original root intentionally suppressed the not-yet-usable
action. This includes one-day access windows.

An already-sent advance reminder trigger must not suppress this positive
`open` reply.

If an exact opening time has passed but the current source remains `unknown`,
do not infer that access is open.

This avoids a future-opening card that never tells residents when the action
actually became usable.

### First rollout presentation boundary

The first state-v2 rollout is intentionally **text-root only**.

CONVEGA is the only source currently ready for publication and does not justify
adding another ambiguous-delivery path for remote media during the state
migration.

The implementation therefore sends:

- one self-contained HTML text root;
- strict HTML text replies.

Photo roots, caption branching and deterministic photo-to-text fallback remain
accepted future presentation behavior below, but are implemented only when a
ready source with a uniquely attributable poster actually needs them.

### 2026-10-06 photo-root implementation checkpoint

The generic lifecycle now supports an optional source-proven `image_url` on
the current `EventAccessRecord`. The image URL remains presentation-only and
is not persisted in lifecycle state.

Root delivery follows the already accepted crash-safe media contract:

- use a photo root only when an exact event-specific image exists and the full
  self-contained root fits Telegram's 1024-character caption limit;
- call the existing `send_photo_url()` path with
  `disable_notification=false`;
- reserve the exact root transaction before either media or text delivery;
- a reviewed deterministic `REMOTE-MEDIA` or local `URL-POLICY` rejection
  may fall back to the equivalent text root under the same reservation;
- timeout, network failure, invalid success structure or any other ambiguous
  photo outcome never falls back to text and leaves the root uncertain;
- later replies are text-only and never repeat the poster;
- a long root that cannot fit a caption uses the existing text-root path
  directly.

No media kind, file ID, image URL, cache, downloader or second transaction is
added to persistent event-access state.

### Media and caption policy

The threaded lifecycle reuses existing event image and Telegram media
infrastructure. It does not introduce a browser or general media downloader.

When photo roots are introduced in a later source rollout, a photo caption
must remain within Telegram's caption limit. That future media implementation
should prefer one compact self-contained photo card over a multi-message
compound transaction. Low-value prose is omitted before material access
conditions.

If the critical card cannot fit safely as a photo caption, prefer one
self-contained **text root** over a two-message photo-plus-overflow transaction.
The poster is desirable but lifecycle correctness and atomic root identity are
more important than forcing media.

If a remote-photo send fails deterministically before any message could have
been created (for example a reviewed Telegram remote-media rejection), the same
reserved root may fall back to the equivalent text card. If delivery is
ambiguous (timeout/network/invalid success structure), do not fall back to text:
keep the uncertain reservation because the photo root may already exist.

The existing shared `send_photo_url()` helper defaults to
`disable_notification=True` because it is also used by quieter publication
flows. Event-access roots are proactive resident alerts and must therefore pass
`disable_notification=False` explicitly. Do not inherit the helper default
accidentally. Threaded follow-up replies keep the normal non-silent
`send_message()` behavior unless a later product decision says otherwise.

## Consequences

- Residents can tap any later lifecycle reply and return to the original
  detailed event card and poster.
- Each event has a stable Telegram conversation anchor.
- Multiple simultaneous registration events can no longer be collapsed into
  one lifecycle message.
- State becomes slightly richer because Telegram root IDs must be retained.
- Ambiguous first-send recovery needs one additional operator input:
  the verified root message ID.
- Planner/delivery must become record-oriented while preserving one uncertain
  send at a time.
- Existing `send_message()` reply support can be reused; no Telegram framework
  is needed.
- Source/presentation probes still determine which sources can provide a good
  rich root card.

## Alternatives considered

### Keep standalone follow-up messages

Rejected. Residents would repeatedly see state changes without a direct jump
back to the event poster and full context.

### Edit the original root instead of replying

Rejected as the default. Editing would erase the chronological lifecycle and
make it harder to notice that a deadline/full/closed transition happened.

### Repeat the poster for every lifecycle change

Rejected. It creates visual spam and wastes the value of Telegram replies.

### Keep batching several events in one registration message

Rejected. One Telegram message cannot be the unambiguous root for several
independent lifecycle threads.

### Use `allow_sending_without_reply=true`

Rejected for normal delivery. Silent loss of threading would hide a stale or
deleted root and make state disagree with what residents see.
