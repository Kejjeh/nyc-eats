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
  Fine dining, Unusual proteins. Means "Google returned it for that search", not "checked on a menu".
- **Score** — the rating shrunk toward the guide's mean by `PRIOR` (150) reviews; the default sort.
- **In scope** — passes `build.leave_out_reason`: four boroughs, operational, rated 4.2+, sit-down.
