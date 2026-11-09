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

## Amendment (2026-11-09, after the first full crawl)

A sample of the 3,431 sites the first crawl read showed two kinds of false evidence: "3-course" lunches
and family meals counted as tasting menus, and one-night holiday menus ("2026 THANKSGIVING DINNER PRIX
FIXE") counted as prix fixe. Now a course count is evidence only from 5 courses up, and a sentence that
names a holiday or event (`menus.ONE_OFF`) is never evidence. Since sites are re-read only monthly,
`build` re-checks every stored sentence against the current rule (`menus.current_evidence`). Effect on
the November crawl: tasting-menu sentences 295 → 173, prix-fixe 322 → 288, omakase unchanged at 186.
