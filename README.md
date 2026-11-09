# nyc-eats

A public, always-current guide to good NYC restaurants: one place to find somewhere to eat or order
from, near home or near a friend, and a data store a Claude chat can query for recommendations
("Italian, $$, open past 10, near this address").

**Status (2026-11-09): design settled, nothing built yet.** This README records the upstream
measurements the design rests on (`sop-verify-upstream`); decisions are in `docs/adr/`.

## Decisions already made (owner, 2026-11-09)

- Own repo, separate from `Kejjeh/omakase` and `Kejjeh/nyc-restaurants`; reuse their match-trust,
  scoring and geo code by copying, not by a shared package (yet).
- Manhattan first, then Brooklyn and Queens, then the Bronx and Staten Island.
- The rating bar is chosen from real data, not guessed.
- Google spend stays inside the monthly free allowance unless the owner approves a specific pass.
- Delivery = Google's flag + search links to the delivery apps + a distance estimate. No scraping of
  delivery platforms.
- Freshness: city data weekly; Google refreshed on a rolling basis inside the free allowance; every row
  shows when it was last checked.
- Ranking: Google rating with Omakase's review-count adjustment; awards and critics are badges.
- Page: list first with a map toggle, sorted by score, filters for cuisine, neighborhood / near an
  address, price, open now / at a time, delivery, takeout, reservable, awards.
- Chat: the page's "ask Claude" box on a phone; a `recommend` command for Claude Code sessions here.

## Upstream measurements (2026-11-09)

### NYC health inspections (DOHMH), `data.cityofnewyork.us/resource/43nn-pn8j`

Free, no key, updated daily, `Access-Control-Allow-Origin: *` (a browser can query it directly).
Rows are one per violation per inspection; `camis` is the stable restaurant ID.

| Count | Restaurants (distinct `camis`) |
|---|--:|
| All in the dataset | 31,463 |
| Inspected since 2025-05-09 (last 18 months) | 25,420 |
| … Manhattan / Brooklyn / Queens / Bronx / Staten Island | 9,929 / 6,498 / 5,817 / 2,241 / 916 |
| Never inspected yet (placeholder date 1900-01-01: new permits) | 3,998 |
| Inspected in the last 18 months but no coordinates (`latitude` 0 or null) | 482 (1.9%) |

Each row carries `dba`, address, `zipcode`, `phone`, `cuisine_description`, `latitude`/`longitude`,
`nta` (the city's neighborhood code, so no point-in-polygon step is needed), `bbl`, `bin`.
Top cuisines in the 18-month set: American 4,176, Chinese 2,156, Coffee/Tea 2,153, Pizza 1,512,
Latin American 1,056, Mexican 1,044, Japanese 960, Italian 913, Bakery/Desserts 898.

### NYC GeoSearch, `geosearch.planninglabs.nyc/v2/search` and `/v2/autocomplete`

Free, no key, CORS `*` on GET. Three test addresses (Midtown, Astoria, Downtown Brooklyn) all resolved
at confidence 0.8, 0.11–0.25 s, ~1.5 KB each. Usable from the page for "near this address".

### Google Places API (New)

Probe of 19 calls, 2026-11-09, using the Omakase key (owner-approved):

- **Text Search with field mask `places.id`** ("Essentials IDs Only": no charge, unlimited):
  10 of 10 open Manhattan restaurants, queried as `"<name> <full address>"`, returned exactly one
  result, and it was the place ID already trusted in `nyc-restaurants`. Matching is free.
- **Place Details**, 3 places × 3 field masks, all HTTP 200. Optional in practice: `priceLevel` and
  `outdoorSeating` were missing for Benoit. Parse every field as optional.
- Field → SKU (Google's Place Details docs), price per 1,000 at the first paid tier, monthly free cap:

| SKU | Fields we would use | $/1,000 | Free / month |
|---|---|--:|--:|
| Essentials (IDs only) | `id` | 0 | unlimited |
| Essentials | `formattedAddress`, `location` | 5 | 10,000 |
| Pro | `displayName`, `businessStatus`, `googleMapsUri`, `primaryType` | 17 | 5,000 |
| Enterprise | `rating`, `userRatingCount`, `websiteUri`, `priceLevel`, `regularOpeningHours`, `currentOpeningHours`, `nationalPhoneNumber` | 20 | 1,000 |
| Enterprise + Atmosphere | `delivery`, `takeout`, `dineIn`, `reservable`, `servesDinner`, `outdoorSeating`, `reviews` | 25 | 1,000 |

The request is billed at the highest SKU among the fields asked for.

### Google Maps Platform terms (read 2026-11-09)

- **Service Specific Terms §3 (all services):** place IDs may be cached.
- **§14.3 (Places API, Legacy and New):** latitude/longitude may be cached for up to 30 consecutive
  days, then must be deleted. Nothing else from Places is listed as cacheable.
- **Terms of Service §3.2.3(a)–(b):** no pre-fetching, indexing, storing or rehosting Google Maps
  Content; no copying and saving business names, addresses or reviews; no caching except as the
  Service Specific Terms expressly permit.
- **§3.2.3(c)(iv):** Places latitude/longitude must not be used for point-in-polygon analysis.
- **§14.2:** Places content must not be shown with a non-Google map.

Consequence: a committed dataset of Google ratings, hours, websites or coordinates is not permitted.
Only `place_id` may be stored. Everything else from Google has to be fetched when it is shown.

## Owner decisions after the recon

- **Google data is stored and published anyway** (ADR 0001): owner-accepted risk, same as `omakase`
  and `nyc-restaurants`.
- **Free allowance only; best-of scope; public site** (ADR 0002): 950 calls per SKU per month,
  the best sit-down places in the Bronx, Manhattan, Brooklyn and Queens, rated 4.2+.
