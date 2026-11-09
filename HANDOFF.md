# Handoff

## State (2026-11-09)

**Live at https://kejjeh.github.io/nyc-eats/** (GitHub Pages, main `/docs`). The payload holds
**6,598 restaurants** (Bronx 665, Brooklyn 1,761, Manhattan 2,653, Queens 1,519), 6,585 with Google
details. Categories: 378 prix fixe, 262 tasting menu, 262 omakase & chef's counter, 99 fine dining,
18 unusual proteins. 608 of the categories come from the restaurants' own sites. City health grades:
A 3,615, B 322, C 90.

November's free allowance is spent: details 950/950, nearby 950/950, themed 103 (no themed items are
left to run). Expected Google charge: $0.00.

| PR | What |
|---|---|
| #1–#3 | Pipeline, page, launch |
| #5, #10 | Menu crawl (ADR 0004) and its precision fix |
| #6, #11, #12 | November data: roster details, themed + nearby, split cells, menus |
| #7 | Ask box, My list, New / Rising flags |
| #8 | Monthly refresh: stale items, scoped crawl, `monthly --live` |
| #9 | Split full nearby cells, health grades, block neighborhoods, smaller payload |

## Next

1. **Monthly refresh, 1st of each month, 9 AM.** This is a scheduled task on the owner's PC: "NYC Eats
   monthly refresh". It runs `python -m nyceats monthly --live`, opens a data PR and does **not** merge
   it. The owner reviews and merges. December's allowance goes first to the 30 remaining roster details
   and the 855 remaining quarter-cells, then to the oldest data for re-checks. It does not run live in
   February or March until the shared-allowance check below is done.
2. **Owner decisions in #4.** Score method, minimum reviews, what counts as sit-down, what sorts to the
   top (only 2 of the top 100 have an award), and price as evidence. Each item has measured options.
3. **Menu PDFs and JavaScript sites.** About 6% of the sites read show no text without JavaScript, and
   PDF menus are skipped. Reading PDFs (one new dependency) would check more menus.
4. **Themed allowance.** 847 themed calls go unused each month once the 14 themes have run. Possible
   uses: new themes (each needs words in `build.THEME_WORDS`, ADR 0003), or re-running the themes monthly
   (stale items do this after 28 days).

## Open owner decisions

All in #4, with numbers:
1. Score method (shrinkage vs Wilson): the two now share 9 of the top 10.
2. Minimum reviews: 21 rows have fewer than 20.
3. Sit-down by type: 16 places Google says serve dine-in dinner are left out by type (Katz's, Terroir…).
4. What sorts to the top.
5. Price as tasting-menu evidence: 179 price-only tags whose own site was read and says nothing.

Also: **shared place_ids in the roster.** 25 place_ids carry two roster rows in nyc-restaurants. Most
are one room named twice; a few are two businesses (Contra / Bar Contra). They are merged here; the
source fix belongs to nyc-restaurants.

## Known limits

- **The ledger sees only this repo's calls.** Google's free allowance is per billing account. ADR 0002
  assumes omakase and nyc-restaurants use legacy Places SKUs that don't share these caps. That is not
  verified. Check Google Cloud billing (the SKU report for November) **before February**, when
  Restaurant Week work resumes. Then record the answer here, so the monthly task may run live in
  February and March.
- **Ledger safety:** a live run holds `data/discover.lock`; every reservation re-reads the ledger under
  `data/quota_ledger.lock`; a copy at `~/.nyceats/quota_ledger.json` wins if the repo copy is ever
  rolled back. A killed run can leave a lock file: delete it only when no run is going.
- **The key** is read from omakase's gitignored `scripts/config.py` when neither the env var nor
  `./config.py` has one (`keys.py`).
- **Menu evidence** reads a site's home page and up to 3 menu pages. A site that blocks robots, errors or
  needs JavaScript is "not checked", never "checked and found nothing".
- **Freshness** compares months: the first flags appear after the December build.
