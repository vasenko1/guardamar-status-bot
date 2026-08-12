# 0036: Operator-triggered poll and channel engagement steps

- Status: Accepted
- Date: 2026-08-12

## Context

The 2026-08 product review found that the channel is one-way while the
highest-engagement native Telegram formats are polls and an attached
discussion group. The product principles forbid scheduled noise, resident
processes, and vote collection, so any interaction surface must stay
manual, bounded, and stateless.

## Decision

- Add one bounded `sendPoll` capability to the existing Telegram client and
  one `poll` operator command:
  `python -m telegrambot poll "<вопрос>" "<вариант>" "<вариант>" …`.
  Polls are anonymous, use Telegram's native rendering and counting, and
  the bot stores nothing and never reads votes. The command is manual only
  and is never scheduled; a failed send is retried by the operator, not by
  code. Validation enforces Telegram's 300-character question and 2–10
  option limits before any network use.
- Record the manual channel steps in
  `research/2026-08-12-product-review-and-growth.md`: enable reactions on
  the channel, attach the public group as its discussion group, and pin the
  drafted onboarding message. These are Telegram settings, not code.
- Suggested cadence from the review: at most one poll per month, asking
  what to add or drop; silence remains the default.

## Consequences

- Benefits: a native interaction surface with zero storage, zero schedule,
  and zero AI; results are visible to everyone in Telegram itself.
- Costs: one more Telegram client method and CLI branch to maintain.
- Follow-up: none until the operator observes real poll usage.

## Alternatives considered

- Collecting votes through `getUpdates` for adaptive content — rejected:
  requires update history and a resident poller, both prohibited.
- Scheduled recurring polls — rejected: scheduled noise violates the
  silence-over-noise principle.
