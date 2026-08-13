# Feria de Comercio 2026 programme follow-up

## Observed problem

The first preview after deploying commit `2b45f2e` on 13 August showed only
`FERIA DEL COMERCIO`, with no time or useful programme detail. That preview
read the municipal catalog created by the phone's 05:10 sync, several hours
before the new Todo Cultura supplement reached the device in the midday
deployment.

## Text source found

Todo Cultura Vega Baja reproduces the August municipal agenda attributed to
the Ayuntamiento de Guardamar. Its REST document was modified at
`2026-08-12T22:18:56` and contains a dated programme for 13–16 August at
Avenida de los Pinos. The 13 August section states:

- inauguration at 18:00 with 16 participating businesses;
- cookie workshop at 18:30;
- artists' exhibition and children's workshop at 19:00;
- candle workshop at 19:30;
- `Faüla`, by `Dos en vilo`, at 21:30;
- DJ Jesús at 23:00.

Source:
`https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-inauguracion-de-la-feria-de-comercio-guardamar-2026-con-16-participantes-dentro-de-la-agenda-municipal-de-agosto-del-ayuntamiento/`

The official public Mayor channel independently posted on 13 August at 07:53
that the day's programmed activities were taking place at the Feria del
Comercio. The text alone does not contain the schedule, so it corroborates the
occurrence but is insufficient as the detailed automated source.

## Product decision

The detailed source contains many individual lines that would overwhelm the
morning digest, and one bounded LLM extraction did not consistently return all
of them. Use the ADR 0039 reviewed-data path to replace the sparse multi-day
row and any separately extracted fair acts with one concise, dated summary per
day. Preserve the published first activity time and Avenida de los Pinos; do
not infer an end time.
