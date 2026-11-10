# Handoff

## State (2026-11-10)

**Live at https://kejjeh.github.io/nyc-eats/** (GitHub Pages, main `/docs`). The payload holds
**6,433 restaurants** (Bronx 601, Brooklyn 1,729, Manhattan 2,637, Queens 1,466), 6,420 with Google
details, built under the issue #4 rulings (ADR 0005, 0006). The page opens on the 425 award winners.
Categories: 352 prix fixe, 221 tasting menu, 255 omakase & chef's counter, 99 fine dining, 17 unusual
proteins. 662 of the categories come from the restaurants' own sites, including 690 PDF menus read on
2026-11-10. 76 rest on price (51 fine dining, 25 where the site could not be read). City health grades:
A 3,602, B 320, C 88.

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
   it. The owner reviews and merges. It does not run live in February or March until the
   shared-allowance check below is done. What December 1 will spend (dry run, 2026-11-10):
   - **details:** the 30 roster places still without Google details;
   - **nearby:** 950 of the 2,363 nearby searches still to run (split cells; a search that comes back
     full adds four more), so the grid takes about three months to finish;
   - **themed / fill (text searches):** the 56 themed searches ran on 2026-11-09 with a rating filter
     Google rounded up to 4.5 (ADR 0002 amendment). They count as never run until they are re-run with
     `plan.SEARCH_MIN_RATING`, which is planned for November's unused text searches, followed by fill
     searches.
   The end-to-end chain (spine, seed, dry run, build, menus, build) was run without Google on 2026-11-10:
   exit 0, 6,433 restaurants, and only files the task is allowed to commit changed.
2. **JavaScript-only sites.** About 6% of the sites read show no text without JavaScript, so they stay
   "not checked". PDF menus are read since 2026-11-10 (ADR 0004 amendment).
3. **The Pool** (Google type event venue) is out under ADR 0005; adding one place by hand would need a
   pin mechanism this repo does not have.
4. **Text-search allowance.** The 56 themed searches use at most 168 of the 950 text searches a month.
   Fill searches (GLOSSARY) take the rest while full nearby squares remain; after that, new themes
   (each needs words in `build.THEME_WORDS`, ADR 0003) are the other use.

## Owner decisions

Issue #4 was ruled on 2026-11-10 ("Yes, all five"):
1. Score method: keep the shrinkage score, not Wilson (ADR 0006).
2. Minimum reviews: 20 (ADR 0005).
3. Sit-down: delis, sandwich shops, cafes and wine bars that Google says serve dine-in dinner are in;
   bars stay out (ADR 0005).
4. What sorts to the top: the page opens on the award winners, with an Everything button (ADR 0006).
5. Price as evidence: counts for fine dining always, and for tasting / prix fixe / omakase only when the
   restaurant's own site could not be read (ADR 0003 second follow-up). PDF menus are read first.

No owner decision is open.

Also: **shared place_ids in the roster.** 25 place_ids carry two roster rows in nyc-restaurants. Most
are one room named twice; a few are two businesses (Contra / Bar Contra). They are merged here; the
source fix belongs to nyc-restaurants.

## Known limits

- **A PDF gets 30 seconds.** pypdf has no time limit, so `menus.pdf_text` reads each PDF in its own
  process and stops it after `PDF_SECONDS`. A stopped PDF is listed in the site's `pdf_timeouts` and counted
  as `pdf_timeouts_now` in the crawl summary. It does not change the site's status, so the site can still
  read as "names no tasting menu"; if that count is ever more than a handful, look at those sites.
- **97 sites answered 429 (too many requests)** to the 2026-11-10 re-read: 97 different small-restaurant
  domains, which points to one shared host or ordering platform limiting the crawl (not checked).
  They count as "not read", so price still counts for them; the next monthly crawl retries them.

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
