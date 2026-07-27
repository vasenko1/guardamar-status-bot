# ADR 0009: Explicit Policía Local traffic notice

## Status

Accepted

## Context

The official Policía Local Guardamar site has no stable live traffic feed, but
its festival traffic page contains one explicit restriction with affected
destinations, access route, reason, and a 15–29 July validity window. A linked
historical PDF has no current year and describes different routing.

## Decision

- Fetch `https://policiaguardamar.com/cortecallefiestas.html` once during the
  morning run as an optional source.
- Show one compact traffic line only from 15 through 29 July and only while
  the freshly fetched page still contains the complete explicit statement:
  Centro de Salud, bus terminal, C/ San Francisco, closure of the remaining
  approaches, festival reason, and date range.
- Omit changed, incomplete, unavailable, or out-of-window content.
- Do not parse the historical PDF, scrape Facebook, infer restrictions, cache
  notices, or treat the page as a general traffic feed.

## Consequences

The digest gains useful official festival access information with one bounded
HTML request and no dependency. The strict adapter intentionally misses new
notice formats until they are reviewed, which is safer than publishing an
incorrect restriction.

## Alternatives rejected

- General-purpose traffic scraper: the site has no consistent notice feed.
- Historical PDF parsing: its freshness and routing cannot be trusted.
- Keyword-based summaries: they could turn unrelated text into a restriction.
