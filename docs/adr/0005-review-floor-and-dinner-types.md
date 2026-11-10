# ADR 0005 — 20 reviews or more; delis, cafes and wine bars that serve dinner are in

- **Date:** 2026-11-10
- **Status:** Accepted (owner ruling on issue #4, items 2 and 3: "Yes, all five")

## Context

Measured on the November guide (6,598 restaurants):

- **Thin ratings.** 170 restaurants had fewer than 20 reviews and 331 had fewer than 50. A 5.0 from 17
  reviews says little. None of the 170 holds an award; 4 award winners that opened recently (Odo East
  Village, HWARO, Muku, l'abeille à côté) have between 20 and 50.
- **Sit-down by type.** `leave_out_reason` dropped places by Google primary type (bar, deli, cafe…).
  For 15 of them, Google also says dine-in and serves dinner: 9 bars (Double Chicken Please, three Stout
  NYC pubs, Fillmore's Tavern, Harlem Hops…), Katz's Delicatessen (deli), Mile End Deli (sandwich
  shop), Terroir (wine bar), Choice Market and Little Chef Little Cafe (cafes), and The Pool (event
  venue).

## Decision

1. **Review floor.** A restaurant needs `build.MIN_REVIEWS` = 20 Google reviews to be in the guide. A
   row below it is counted as "fewer than 20 reviews" in `meta.left_out`. A row with no review count
   at all is left out as "no review count" (none today), so a seed that loses its counts shows up.
2. **Dinner types.** A place whose primary type is in `build.DINNER_TYPES` (deli, sandwich shop, cafe,
   wine bar) stays in when Google says **both** dine-in and serves dinner. Both must be `True`; unknown
   is not yes. Bars, pubs, cocktail bars and the rest of `plan.EXCLUDED_PRIMARY` stay out even then:
   a cocktail bar or sports pub with food is not a dinner restaurant.

## Consequences

- About 170 places leave the guide and 5 come back (Katz's, Mile End Deli, Terroir, Choice Market,
  Little Chef Little Cafe).
- The Pool stays out (Google calls it an event venue). Adding a single place by hand would need a
  pin mechanism this repo does not have.
- Discovery is unchanged: Nearby Search still excludes these types (`excludedPrimaryTypes`), so a
  deli or cafe enters only through the roster or a themed search. Searching for them would spend the
  allowance on many places this rule then drops.
- The score method itself is unchanged (ADR 0006).
