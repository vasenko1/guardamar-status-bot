# SafeBeach October service horizon and late-start coverage gap

- Date: 2026-10-10
- Scope: SafeBeach annual guard and October later-day recovery
- Status: reviewed production/source investigation

## Questions

1. Is the internal 15 October SafeBeach cutoff still correct for 2026?
2. Why was there no beach root on 9 October and still none by 13:17 on
   10 October?
3. Can the fix stay bounded without increasing unrelated source polling?

## Service horizon evidence

EFE reported on 4 October 2026 that Guardamar mayor José Luis Sáez stated the
salvamento y socorrismo service remains active through 31 October on Playa
Centro and La Roqueta. Onda Cero reproduced the same EFE statement on
5 October.

This evidence is used only to set the bot's internal query guard. Runtime beach
facts continue to come exclusively from the municipality-linked SafeBeach page
and still require current, active, non-ended records.

Sources:

- `https://efe.com/comunidad-valenciana/2026-10-04/mueren-dos-jovenes-ahogados-en-una-playa-de-guardamar-de-segura-alicante/`
- `https://amp.ondacero.es/emisoras/comunidad-valenciana/vega-baja/informativos/jovenes-ahogados-guardamar-arrastrados-corrientes-playa-els-vivers-eran-pareja-estaban-vacaciones_202610056ac3942ba4297764c3aa0fc5.html`
- `https://info.safebeach.es/guardamar-del-segura`

## 9 October production evidence

The managed cron was present and `crond` was running.

The 10:10-10:40 update cycle executed all seven checkpoints and logged
`SKIP: no current beach facts became available` each time. The later October
operational windows executed as scheduled. No `SafeBeachError` was logged,
and no beach candidate entered operational state.

The next-day read of `PublicationState` returned no morning record for
9 October because that state file intentionally stores only the current local
day. This is expected behavior and is not evidence that the 9 October Morning
Digest was missed.

Conclusion: available evidence does not show a transport/parser failure on
9 October; the source did not yield an eligible current active status at the
sampled checkpoints.

## 10 October production evidence

At 13:17:15 CEST a one-request read-only production probe returned a current
SafeBeach page dated 2026-10-10.

Recognized Centre / Babilònia values were:

- `hasActividad=true`;
- `serviceEnded=false`;
- `textoBandera='Bandera amarilla'`;
- `colorBandera='#f7d40e'`;
- `hora='10:00'`;
- `waterTemp='25º C'`;
- `oleaje='Débil'`;
- `medusas='No'`;
- `viento='1.8 m/s'`;
- `windDeg=358.53`.

The other five recognized records were inactive at that exact sample.

The production normalizer returned a current yellow Centre status, including
25 C water, slight sea state, no jellyfish and update time 10:00.
`is_current_status()` returned true.

At the same time:

- `beach_message_id=None`;
- `beach_root_status=None`;
- `beach_pending=null`;
- `beach_ready=[]`.

The 10:10-10:40 cycle had logged no current beach facts. The 12:00 operational
run produced CAMS logs but no `WAIT: beach change confirmation is pending`,
so it did not observe an eligible SafeBeach status. Therefore the official
source became usable after the last sampled point that could create a pending
candidate and before the 13:17 probe.

A prior 6 October production probe found Centre still carrying operational
values but already `serviceEnded=true` with `hora='14:00'` at 15:33. This
does not prove a universal daily closing time, but it demonstrates that a short
October active window can end around the next old 14:00 primary checkpoint.

## Failure mode

The normal October later-day cadence inherited the shoulder schedule:

- 12:00 primary;
- 14:00 primary;
- 16:00 primary;
- 18:00 primary;
- +5/+10 confirmations only while pending.

If the first eligible status appears after the 12:00 sample, the bot waits
until 14:00. On a short service day that can delay the first root by almost two
hours or race `serviceEnded=true`.

The parser and active-service contract are not the defect. The gap is purely
sampling cadence.

## Reviewed fix

Keep the architecture unchanged and add only two October SafeBeach
initial-recovery opportunities:

- 13:00, confirmations at 13:05 and 13:10 only if pending;
- 13:30, confirmations at 13:35 and 13:40 only if pending.

The two recovery primaries fetch only while today's beach root still lacks a
confirmed SafeBeach status. Once a SafeBeach status has been published, these
extra windows become no-op for SafeBeach and the normal later-change cadence
continues unchanged.

The existing 12:00/14:00/16:00/18:00 windows remain.

The scheduler keeps these recovery checkpoints SafeBeach-only:
`check_environment=false` and `check_aemet=false`, so they do not add CAMS,
Meteosalud, AEMET or Mayor-channel requests.

This is deliberately smaller than a 30-minute all-day polling redesign. It
addresses the observed 12:00-14:00 late-start gap with two bounded conditional
recovery opportunities, reuses the existing confirmation state machine, adds no
new state and keeps winter HTTP at zero.

## Logging gap

A successful SafeBeach request with no eligible active status previously had
no explicit operational log line. This made a healthy empty response look like
a skipped check.

The reviewed change logs both successful cases:

- current normalized flag records available;
- no eligible current beach status.

Transport/contract errors continue to use the existing `SB-...` diagnostics.

## Decision

Implemented architecture is recorded in ADR 0106.