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
- events relevant today.

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

### Future Feature

The architecture reserves one additional feature slot. Its purpose, inputs,
and output are intentionally undefined. It must not be designed or implemented
until a concrete user need is approved.

## Out of scope

- General news aggregation
- Continuous alerts or real-time emergency monitoring
- Replacing official emergency or municipal channels
- Conversational AI or generated advice
- General AI summarization, classification, or ranking outside the strict
  Policía Local traffic fallback
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

The MVP performs one short morning execution: collect the currently approved
official sources, build the digest, publish it to one configured Telegram
destination, save the successful local date, and exit. It has no resident
scheduler, background collector, or cache synchronization. A separate optional
operator listener may use one idle Telegram long poll solely for allowlisted
private `/preview`; it never publishes or changes publication state.
