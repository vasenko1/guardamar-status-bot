# Bus Sigüenza airport timetable and fare investigation

Date checked: 2026-08-14, Europe/Madrid.

## Official sources

- Date-specific operator search:
  `https://www.bus-siguenza.com/index.php?page=urbano`
- Its bounded form endpoint:
  `https://www.bus-siguenza.com/wbus/procesa.php`
- Fare document exposed by that response:
  `https://www.bus-siguenza.com/wbus/tarifas/2026_CE-714%20BENFERRI-ORIHUELA-GUARDAMAR-ALACANT_firmado%20%281%29.pdf`

The fare document is issued by Generalitat Valenciana, Dirección General de
Transportes y Logística, for concession CE-714. It is electronically signed,
has validation CSV `IASD3ZXP:SVM8BJCD:I6JIGCPU`, and states an effective date
of 1 February 2026. The observed SHA-256 is
`22cca0e0ee983a24d46fba834d5b3358f6d068db26e4d9f5cb236a58069a8504`.
The server returned ETag `"349ae-64a60a18e365f"`, Last-Modified
`Mon, 09 Feb 2026 09:19:08 GMT`, and `304 Not Modified` when both validators
were sent on 14 August 2026.

## Observed date-specific results

The same outbound times appeared for every sampled date:

- Guardamar to airport: `07:50`, `12:05`, `15:05`.

The return service changed with the requested date:

- 14, 15 and 16 August 2026: `08:45`, `13:00`, `16:30`, `20:30`.
- 1 September and 25 December 2026, 1 January and 15 February 2027:
  `08:45`, `10:00`, `13:00`, `16:30`, `20:30`.
- 1 July 2027: `08:45`, `13:00`, `16:30`, `20:30`.

The sample proves that one permanent timetable is unsafe. It does not prove a
calendar rule, so public copy must use the operator result for the actual date
instead of inferring fixed summer and winter boundaries.

The operator response gives these exact map points:

- Guardamar bus station: `38.087834,-0.655759`.
- Alicante-Elche airport stop: `38.282222222222,-0.55805555555556`.

## Fare finding

Page 3 is the official tariff matrix for line 3,
`ALMORADÍ - GUARDAMAR - AEROPUERTO`. In the standard-fare airport row, the
Guardamar column states 32 km and `2,95 €`. Other rows contain reduced fares,
but the compact public message should show only the standard single ticket and
link it to the complete official fare document.

## Automation boundary

- Make one small official POST for the current local date during the existing
  05:00 transport sync.
- Strictly require both directions, ordered unique times, one coordinate per
  direction, and plausible Guardamar and airport bounds.
- Treat the timetable and fare independently. A missing or ambiguous fare link
  must not hide a valid timetable.
- Fetch the fare PDF conditionally with ETag and Last-Modified. Download a
  changed PDF twice identically before parsing it.
- Run `pdfinfo` and `pdftotext -layout` only after a changed PDF. Require the
  official authority, concession, line 3, signature text, effective date, stop
  order, six airport-row pairs, and the fourth pair for Guardamar.
- Store only one strict normalized schedule/fare snapshot. Never store HTML or
  raw PDFs.
- On a source outage, retain the explicitly dated accepted message. The cached
  normalized snapshot is also sufficient to recreate an accidentally deleted
  message without inventing current data.
- A changed but unsupported fare is omitted. The timetable remains available.
