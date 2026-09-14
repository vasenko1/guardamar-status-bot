# ADR 0064: Immutable morning anchor and semantic operational updates

Status: accepted (2026-09-14)

The 07:30 Morning Digest is an immutable daily snapshot and remains the
reply anchor. Later CAMS, Meteosalud and AEMET changes are compact,
deterministic replies only when user-facing meaning changes. SafeBeach has a
separate seasonal root message and later confirmed beach changes reply to
that root. A small atomic JSON state stores anchors and compact baselines;
there is no database, daemon, new cron, or runtime AI generation.

Legacy state containing replacement identifiers remains readable during the
same-day cutover. New days use the immutable-anchor lifecycle. Source failure,
stale data, or missing data never becomes a false risk-cleared notification.
