# ADR 0003 — A themed search tags a restaurant only with evidence it fits

- **Date:** 2026-11-09
- **Status:** Accepted (owner ruling after the first live run)

## Context

The first live run (7 Text Search calls for "tasting menu" in the Bronx, Manhattan and Brooklyn) tagged
all 97 results "Tasting menu". In Manhattan the results were genuine tasting-menu rooms (Daniel, Atomix,
The Musket Room, Torien, Kono). In the Bronx none of the 11 showed any sign of one: Google ranks by
relevance and fills the page, so where a borough has few tasting menus it returns good restaurants
nearby (Cap't Loui seafood, Nana's Kitchen, Lena Trattoria). 17 of the 99 places had no evidence at all.

## Decision

A theme becomes a category on a restaurant only when Google's own data supports it
(`build.theme_evidence`):

- Google's type is `fine_dining_restaurant` (for the tasting, prix-fixe, omakase and fine-dining themes);
- or the name or editorial summary contains a theme word (`build.THEME_WORDS`);
- or, for the expensive themes only, the price level is $$$ or more ($$$$ for "Fine dining").
  Price is never evidence for a protein theme.

A match without evidence is not tagged; it is counted in `meta.theme_matches_without_evidence`.
The restaurant itself stays in the guide if it is otherwise in scope.

## Consequences

- Fewer, truer categories. Some real tasting menus at $$ with a terse Google summary go untagged until
  the menu crawl (HANDOFF "Next") can add evidence from the restaurant's own site.
- Adding a theme to `plan.THEMES` now requires its words in `THEME_WORDS`; the build raises otherwise.
