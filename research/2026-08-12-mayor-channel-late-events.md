# Late municipal events in the Mayor channel

## Question

Find an authoritative, lightweight source for useful municipal activities
that may be absent from Agenda Guardamar and the monthly cultural programme.

## Observed occurrence

The official Ajuntament Facebook page published `SERES FASCINANTES DEL
MEDITERRÁNEO` for Wednesday 12 August 2026, `09:00–13:00`, at Playa Centro on
Paseo Marítimo with Calle Dr. Fleming. The post describes nature information
and environmental-education workshops.

The public `@AlcaldeGuardamar` Telegram channel independently published the
same occurrence on 11 August at 17:54 local time as post `21456`:

`https://t.me/AlcaldeGuardamar/21456`

Its text includes the exact title, `mañana miércoles 12 de agosto`, the
`09:00 a 13:00` range, `#PlayaCentro`, `#PaseoMarítimo`, an invitation and
municipal hashtags. The public preview is accessible without a Telegram user
session.

## Assessment

The Telegram channel is the preferred automated source because the project
already reads its bounded public HTML preview, while Facebook is less stable
and would add another scraped surface. The Telegram post supplies enough text
for deterministic current-date, time, place and prospective-event validation;
no image OCR or model call is needed.

The channel also carries ordinary news and reports about completed activities,
so a general event feed is unsafe. Accept only complete invited occurrences
and fail closed on missing fields. Facebook remains a manual corroboration
source, not an automated dependency.
