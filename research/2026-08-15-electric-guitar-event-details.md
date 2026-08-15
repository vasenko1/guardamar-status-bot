# Electric-guitar workshop detail investigation

Checked: 2026-08-15, Europe/Madrid.

## Source

Todo Cultura Vega Baja published an event-specific page:

`https://todoculturavegabaja.es/eventos/guardamar-del-segura-evento-taller-de-guitarras-electricas-para-jovenes-de-12-a-30-anos-dentro-de-la-agenda-municipal-de-agosto-del-ayuntamiento/`

The page identifies the municipal activity on 15 August from 19:00 to 21:00
and explicitly states:

- electric-guitar workshop for young people aged 12 through 30;
- participants may start from zero or improve chords, scales, rhythms, solos,
  technique, improvisation, group practice, and jam sessions;
- registration at Centro Social Juvenil or by WhatsApp at 609 00 67 54.

The public digest should keep a compact Russian summary rather than reproducing
the full description:

`Мастер-класс по электрогитаре (для молодёжи 12–30 лет; можно начать с нуля или улучшить технику и игру в группе)`

and a separate registration row:

`регистрация: Centro Social Juvenil или WhatsApp 609 00 67 54`

## Root cause

The WordPress API exposed many event-specific pages for the same date. The
collector bounded full downloads to three pages, selected primarily by
freshness, and then copied a processed date to every other same-date candidate.
A generic or unrelated newer page could therefore prevent this detail page
from ever being read.

## Resolution boundary

Parser version 7 introduced the three-page priority and per-candidate
completion. Version 8 additionally binds participation to its explicit date
and time, preserves bounded beginner and group-format facts, and resumes large
sections through bounded content hashes. The current occurrence also has an
evidence-backed reviewed correction so a live in-place refresh does not depend
on the supplemental site being available at that moment.
