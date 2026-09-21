# ADR 0064: Immutable morning anchor and semantic operational updates

Status: accepted (2026-09-14)

The 07:30 Morning Digest is an immutable daily snapshot and remains the
reply anchor. Later CAMS, Meteosalud and AEMET changes are compact,
deterministic replies only when user-facing meaning changes. Late CAMS compares
the current and remaining local hours while retaining historical samples for
its rolling windows. Valid Meteosalud levels, including zero, replace only the
prior verified level; stale or unavailable data preserves it.

CAMS keeps the mutable source cache separate from the raw cycle that produced
the accepted public semantic baseline. A remotely fetched production cycle is
first saved as an exact cycle-addressed candidate using an atomic process-safe
temporary file. After the public outcome is known, that exact candidate may be
promoted to the accepted snapshot. Reconstruction of an older accepted cycle
reads only the accepted snapshot and never rewrites a candidate. Publication
state stores only compact semantic facts and has no source-cache side effects.
Operator previews use a disposable CAMS cache copied from the mutable last-good
file, so preview activity cannot overwrite production cache or candidates.
The late environment read, compare, Telegram send and semantic-state update
share the existing publication-state lock. If raw snapshot promotion fails
after a Telegram update has already succeeded, the semantic state still
advances so the same public alert is not deliberately repeated.

SafeBeach is fully separate from the 07:30 Morning Digest: morning
publication, preview and `refresh-current` never request or render SafeBeach
data. Scheduled SafeBeach requests are allowed only from 1 June through
30 September.

The 10:10–10:40 update cycle checks SafeBeach every five minutes. The first
valid current response containing at least one verified beach flag creates one
standalone daily beach root immediately. Every later valid response in that
window edits the same root in place. Each edit represents that response as a
whole; records from separate SafeBeach responses are never merged, so an
absent beach is not kept alive as a potentially stale current flag.

After the 10:40 update, the SafeBeach snapshot in an existing root is frozen
and becomes the baseline for the operational monitor. Later confirmed flag or
jellyfish changes are separate replies to that root rather than silent edits.
If no root was created by 10:40, the first later confirmed status may create
one as a recovery path and does not also emit a duplicate initial reply. If a
root disappears before a later reply, it may be recreated from confirmed
state. Newer explicit Mayor bathing restrictions remain an independent
safety signal and may refresh the same root; this decision does not redesign
their delivery.

Public flag blocks are phone-first: the flag colour/type is on its own line,
beach names follow on rows of at most three names, and the bathing meaning is a
separate final line. Mixed states are ordered red, yellow, then green. An
explicit bathing prohibition suppresses contradictory permission wording.

A small atomic JSON state stores anchors and compact baselines; there is no
database, daemon, new cron, runtime AI generation, or project-wide scheduler
lock. Legacy state containing replacement identifiers remains readable during
the same-day cutover. New days use the immutable-anchor lifecycle. Source
failure, stale data, or missing data never becomes a false risk-cleared
notification.
