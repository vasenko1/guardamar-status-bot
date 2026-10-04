# 2026-10-04 AEMET short-warning monitoring gap

## Scope

This note records the production evidence that led to ADR 0099. It is an
incident/source observation, not a stable runtime contract.

## Production evidence

On 4 October 2026 the prepared 07:15 AEMET snapshot completed with the warning
product available and an empty normalized warning set.

The operational monitor then observed:

- 11:00: no confirmed AEMET warning change;
- 15:00: the CAP check failed with an AEMET HTTP 503;
- 19:00: the CAP check completed without a confirmed warning change.

At approximately 23:34 Europe/Madrid, a direct production read through the
existing AEMET adapter returned two normalized Guardamar-zone CAP warnings:

1. yellow rain warning, valid 22:00-23:59:59, probability 40-70%, with
   one-hour accumulated precipitation parameter 20 mm;
2. yellow thunderstorm warning, valid 22:00-23:59:59, probability 40-70%.

Both records were for `Litoral sur de Alicante`, the configured Guardamar
warning zone. The existing deterministic renderer recognized both event labels.

The exact AEMET CAP publication/issue timestamp was not established. The
supported conclusion is narrower: the warning set was not observed by the
successful 19:00 bot check, was present by approximately 23:34, and the warning
validity began at 22:00.

## Diagnosis

The parser, warning-zone filter, API key, CAP download path and renderer were
all functioning when tested later that night. The direct production failure was
therefore the scheduling blind spot: 19:00 was the final AEMET checkpoint, so a
warning becoming available later in the evening could begin and expire before
the next prepared morning snapshot.

The 15:00 HTTP 503 was not the direct cause because the later 19:00 check
succeeded, but the sequence also demonstrates why sparse checkpoints amplify
ordinary transient source failures.

Review of the operational state machine also found pre-existing coupling that
would become more important if AEMET frequency were increased:

- an existing `warning_ready` value could suppress later AEMET fetches;
- warning pending state could suppress a SafeBeach primary sample;
- SafeBeach confirmation pending state could return before AEMET delivery;
- AEMET finalization also committed `beach_ready`;
- the old AEMET checkpoints doubled as CAMS/Meteosalud recovery triggers.

These are addressed by ADR 0099 without adding a new source or resident
process.

## Design boundary

The reviewed remediation uses CAP-only one-shots at minute 51 from 07:51
through 23:51. SafeBeach and CAMS/Meteosalud keep their previous request
cadences. The post-23:51 overnight interval remains an explicit product
boundary rather than being silently converted into a 24-hour emergency
monitor.
