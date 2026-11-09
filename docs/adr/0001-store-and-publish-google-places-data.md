# ADR 0001 — Store and publish Google Places data, knowingly against Google's terms

- **Date:** 2026-11-09
- **Status:** Accepted (owner decision)

## Context

Google's Maps Platform terms (read 2026-11-09, quoted in README) allow caching only `place_id`
indefinitely and latitude/longitude for 30 days. They forbid storing, indexing or rehosting other
Places content (ratings, hours, websites, names, addresses, reviews), using Places coordinates for
point-in-polygon, and showing Places content on a non-Google map.

The compliant design (store `place_id` only, fetch everything else live when shown) cannot rank or
filter the whole city by rating, which is the main thing the owner wants the site for.

## Decision

The guide stores Google Places data in this repo and publishes it on a public GitHub Pages site,
the same way `Kejjeh/omakase` and `Kejjeh/nyc-restaurants` already do. The owner accepts the risk:
Google may suspend the Cloud project behind the key, which the other two repos also use.

Nothing in `omakase` or `nyc-restaurants` changes because of this ADR.

## Consequences

- Every Google-derived field carries the date it was fetched, so staleness is visible.
- Neighborhoods come from the city's own `nta` code (DOHMH), not from Google coordinates.
- If Google ever objects, the fallback is ready: keep `place_id`, delete the rest, fetch live.
- The API key lives only in a gitignored file and is never committed or printed.
