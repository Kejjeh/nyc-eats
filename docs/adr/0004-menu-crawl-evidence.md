# ADR 0004 — The restaurant's own site is evidence for a category

- **Date:** 2026-11-09
- **Status:** Accepted (owner asked for the menu crawl recommended after launch)

## Context

ADR 0003 tags a category only with evidence from Google's listing, and its follow-up kept price ($$$+)
as evidence until a menu crawl could check restaurants' own sites. About half of the 53 tags resting on
price alone looked wrong. Google's listing also never says what a tasting menu costs.

## Decision

`python -m nyceats menus` reads each place's website: robots.txt first, the home page, then up to 3
same-site links that look like a menu (no PDFs), 10 s timeout, 2 MB per page. `menus.MENU_WORDS`
looks for whole phrases ("tasting menu", "10-course", "prix fixe", "omakase", "chef's counter"),
narrower than `build.THEME_WORDS` because a whole site is long. The matching sentence and any dollar
amounts in it are stored in `data/menus.json`.

In `build`:

- A site that names the meal confirms a themed match before price is consulted, so the reason shown
  becomes "restaurant's own site" instead of "price $$$".
- A site that names the meal tags the category even when no themed search returned the place. A
  restaurant saying "our 14-course tasting menu" on its own site is better evidence than a search hit.
- Only a site read with `status: ok` counts. Robots-blocked, failed and JavaScript-only sites are
  "not checked" and change nothing.
- Price stays as evidence (ADR 0003 follow-up ruling). `meta.menus.price_only` counts the tags still
  resting on price alone, split into "site read, does not say" and "site not read", so the owner can
  rule on dropping price with the numbers in hand.

## Consequences

- Each row carries `category_why` (category → reason) and `menu` (date read, prices, the sentence per
  category). The page shows them under "More".
- The crawl is free but visits about a thousand small sites; it re-reads a site only when it is new,
  its URL changed, or it was read 30+ days ago.
- Many restaurant sites render menus with JavaScript or as PDFs; those stay "not checked". Reading
  PDFs is a possible follow-up.
