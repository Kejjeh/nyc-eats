# Glossary

One term, one meaning. Code, docs and the page use these exactly.

- **City spine** — every restaurant the NYC health department (DOHMH) inspected in the last 18 months in
  the four boroughs, one row per `camis`. Free. Source of neighborhoods, ZIP→borough and the grid.
- **camis** — DOHMH's stable restaurant ID.
- **NTA** — Neighborhood Tabulation Area, the city's 2010 neighborhood code on each DOHMH row (`MN17`).
- **Seed** — the open, trusted, 4.2+ rows of the nyc-restaurants award roster, imported read-only.
- **Roster row** — a guide row whose data comes only from the Seed (no Google details yet). `source: roster`.
- **Google details** — hours, price, website, phone, delivery/takeout/reservable from Places. `source: google`.
- **Quota ledger** — `data/quota_ledger.json`: Google calls per SKU per billing month. Code adds before
  each call and refuses past the **cap** (950).
- **SKU** — the Google price line a request bills at, set by its highest field tier.
- **Billing month** — the calendar month in Pacific time (Google's billing clock).
- **Pool** — one stream of planned calls on one SKU: `details`, `themed`, `nearby`.
- **Discovery plan** — every planned call as items with stable ids; finished items are recorded in
  `data/discovery_state.json` and never repeated.
- **Theme** — a priority search ("tasting menu", "wagyu") whose results get a **category** on the page.
- **Category** — the kind of meal a theme stands for: Tasting menu, Prix fixe, Omakase & chef's counter,
  Fine dining, Unusual proteins. Means Google returned it for that search AND its listing gives evidence
  (ADR 0003: type, a theme word, or price for the expensive themes), OR the restaurant's own site names
  the meal (ADR 0004). `category_why` on each row says which.
- **Menu crawl** — `python -m nyceats menus`: reads each restaurant's own website (home page plus up to
  3 menu-looking pages) into `data/menus.json`. Free; obeys robots.txt.
- **Checked on the menu** — the crawl read the site (`status: ok`). A site that could not be read
  (robots, error, JavaScript-only "no text") is *not checked*, never "checked and found nothing".
- **Ask** — the page's plain-English box (`core.parseAsk`): turns "Italian, $$, open past 10, near Union
  Square" into the page's own filters, on the page, free. Words it cannot place are shown as "Not understood".
- **My list** — Saved / Been there marks, kept in the viewer's browser only (`localStorage`).
- **Freshness** — "New to the guide" (not in last month's snapshot) and "Rising" (rating up 0.1+ on 10+ new
  reviews), from `data/history/YYYY-MM.json`, which `build` writes each run. The first month flags nothing.
- **Score** — the rating shrunk toward the guide's mean by `PRIOR` (150) reviews; the default sort.
- **In scope** — passes `build.leave_out_reason`: four boroughs, operational, rated 4.2+, sit-down.
