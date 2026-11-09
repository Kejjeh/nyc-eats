# ADR 0002 — Grow the guide only inside Google's free monthly allowance; best-of scope

- **Date:** 2026-11-09
- **Status:** Accepted (owner decisions Q16–Q23)

## Decision

**Budget.** No paid Google usage. Each Places SKU the guide uses has its own monthly free cap
(Text Search Enterprise, Text Search Enterprise + Atmosphere, Nearby Search Enterprise, Nearby Search
Enterprise + Atmosphere, Place Details Enterprise, Place Details Enterprise + Atmosphere: 1,000 each).
Code caps each at **950 calls per calendar month** in a committed ledger and stops at the cap; it never
spills into paid usage. The owner also sets a daily quota in the Google Cloud console as a backstop.
`nyc-restaurants` (paused until Winter 2027 Restaurant Week, expected late January) and `omakase`
(static) use the legacy Places API, whose SKUs are separate, so they don't compete for these caps.

**Scope.** The best sit-down restaurants in the Bronx, Manhattan, Brooklyn and Queens (Staten Island
later, if wanted). Collect everything rated **4.2+**; the site's rating filter defaults to **4.5**.
Priorities: tasting menus, prix fixe, omakase / chef's counters, unusual proteins.

**Discovery.** Search calls, not per-restaurant lookups: each returns up to 20 places with rating,
review count, price, hours, website, phone (Enterprise) and delivery / takeout / dine-in / reservable
(Enterprise + Atmosphere). Seed first, free, from the `nyc-restaurants` award roster (Michelin, Beard,
NYT): 1,113 open rated venues, 853 at 4.4+.

**Site.** Public, GitHub Pages, built from `nyc-restaurants`' page code and look.

## Evidence (10-call probe, 2026-11-09)

- Every call returned 20 places; text search paged to 60 (3 pages). `minRating` was honored
  (4.0 → lowest returned 4.1; 4.5 → lowest 4.5).
- 200 results → 192 unique; **119 not already in the RW roster**. 155 of 192 rated 4.4+ with 100+ reviews.
- Nearby search by popularity (800 m–1 km circles) found 9–17 places at 4.4+ per call, mostly new:
  Arthur Ave 17 (2 in roster), Astoria 12 (1), Williamsburg 15 (6), Mott Haven 9 (1).
- Field coverage: rating / review count 100%, hours 98%, website 97%, phone 97%, price 88%;
  delivery 93%, reservable 97%, dine-in 100%, editorial summary 50%.
- `primaryType` includes `fine_dining_restaurant` (11 of 192): a free tasting-menu signal. Editorial
  summaries rarely say "tasting menu" (3 of 30), so menu crawling stays the main detector.
- "tasting menu" (60) and "omakase" (20) in Manhattan overlapped by only 2: themed queries reach
  different restaurants.
