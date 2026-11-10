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
  (4.0 → lowest returned 4.1; 4.5 → lowest 4.5). Both were whole steps of 0.5; see the amendment
  below for what a value between steps does.
- 200 results → 192 unique; **119 not already in the RW roster**. 155 of 192 rated 4.4+ with 100+ reviews.
- Nearby search by popularity (800 m–1 km circles) found 9–17 places at 4.4+ per call, mostly new:
  Arthur Ave 17 (2 in roster), Astoria 12 (1), Williamsburg 15 (6), Mott Haven 9 (1).
- Field coverage: rating / review count 100%, hours 98%, website 97%, phone 97%, price 88%;
  delivery 93%, reservable 97%, dine-in 100%, editorial summary 50%.
- `primaryType` includes `fine_dining_restaurant` (11 of 192): a free tasting-menu signal. Editorial
  summaries rarely say "tasting menu" (3 of 30), so menu crawling stays the main detector.
- "tasting menu" (60) and "omakase" (20) in Manhattan overlapped by only 2: themed queries reach
  different restaurants.

## Amendment (2026-11-10): `minRating` is rounded up to a step of 0.5

Google takes `minRating` in steps of 0.5 and rounds a value between steps up, so the 4.2 the text
searches sent behaved as 4.5. Of the 938 text-search results to 2026-11-10 (876 themed, 62 fill)
none was rated below 4.5, while 2,741 of the guide's 6,433 rows are rated 4.2–4.49. The probe above
missed it because it tried only 4.0 and 4.5.

Text searches now send `plan.SEARCH_MIN_RATING`, the step at or below the 4.2 floor (4.0). The floor
itself does not move: `build.leave_out_reason` still leaves out anything below 4.2, so the 4.0–4.19
places a search now also returns are stored and never shown. Each text search records the
`min_rating` it ran with, and one run with another value (or before the value was recorded) counts as
never run, so the 56 themed searches and the fill searches already sent run again.
