# 0090: Thread one-off registration updates under one event root

- Status: Accepted
- Date: 2026-10-03
- Implementation: Pending source/presentation probes

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
process a small bounded number of independent publications sequentially, but
each send has its own crash-safe reservation and commit.

No queue, worker, database or long-lived process is introduced.

### Root publication absorbs same-run facts

When the first root is created, it should include every material registration
fact already known for that record.

For example, first discovery of an already-open registration whose deadline is
tomorrow produces one rich root card that includes that deadline. It must not
immediately generate a second deadline reply in the same run.

Triggers represented in the root are acknowledged atomically with successful
root delivery.

### Persist Telegram root identity separately from semantic baseline

The lifecycle state moves to a new bounded schema that keeps:

- semantic baseline;
- audience-announced IDs;
- sent trigger IDs;
- per-record Telegram root metadata;
- at most one uncertain outbound publication.

Conceptually:

```text
root_messages[record_id] = {
    message_id,
    published_at,
    media_kind
}
```

Telegram root metadata is presentation/delivery state. It is not source
evidence and must not participate in registration-state comparisons.

Root metadata is pruned with the corresponding expired lifecycle record.

### Preserve audience knowledge separately

`announced_record_ids` remains semantically useful even after root IDs are
added.

A migrated/legacy record may be known to the audience without a recoverable
root message ID. Such a case must not be rewritten as "never announced" merely
because threading metadata is absent.

### Migrate state v1 fail-safe

The deployed v1 state must be accepted and migrated deterministically to the
new schema without deleting baseline or sent-trigger history.

Existing v1 records have no root metadata. The current production baseline is
silent, so migration itself creates no Telegram publication.

No Telegram root ID may be invented during migration.

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
eligible when it adds actionable information that was intentionally suppressed
before the start boundary, such as the now-active registration form/contact.

This avoids a future-opening card that never tells residents when the action
actually became usable.

### Media and caption policy

The threaded lifecycle reuses existing event image and Telegram media
infrastructure. It does not introduce a browser or general media downloader.

A root photo caption must remain within Telegram's caption limit. The first
implementation prefers one compact self-contained photo card over a
multi-message compound transaction. Low-value prose is omitted before material
registration conditions.

If the critical card cannot fit safely as a photo caption, the implementation
must use a deterministic reviewed fallback rather than truncate deadlines,
registration actions or participation requirements.

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
