# ADR 0006 — Keep the shrinkage score; the page opens on the award winners

- **Date:** 2026-11-10
- **Status:** Accepted (owner ruling on issue #4, items 1 and 4: "Yes, all five")

## Context

**Score method.** The score shrinks each rating toward the guide's mean by `build.PRIOR` = 150
reviews (the nyc-restaurants method). The README once named Omakase's method instead: the Wilson
lower bound (z = 1.96) × 0.97. On the November guide the two orders shared only 4 of their top 10.
Wilson treats a 5.0 average as if every review were 5 stars, so its top 10 filled with perfect scores
on a few hundred reviews (Persone NYC, D'Romano's Pizza, Yough, Halal Stop).

**What sorts to the top.** After the nearby grid ran, the top of "Best" was high-volume, high-rating
places such as Hibachi Omakase (5.0, 4,068 reviews), Mira Mediterranean & Hookah Lounge (4.9, 9,951)
and Empire Steak House Times Square (4.9, 9,491). Only 2 of the top 100 held an award under either
method; 75 of the 77 places rated 4.9+ on 1,000+ reviews came from the grid. The 421 award winners
had a median rank of 3,369.

## Decision

1. **Keep the shrinkage score** (`build.PRIOR` = 150). Do not switch to Wilson.
2. **The page opens on the award winners** (Michelin, James Beard, New York Times; `core.inScope`,
   `DEFAULT_SCOPE = 'awards'` in `app.js`). An "Everything" button shows the whole guide. Both buttons
   show how many restaurants match the current filters, and an empty award list says how many match in
   Everything. Ask and the quick views (presets) search Everything, because they are fresh questions
   about the whole guide: only 6 Bronx restaurants hold an award. The score is unchanged: no award
   bonus, so no weight had to be chosen.

## Consequences

- The default list is a critics' list (421 restaurants, leaning to Manhattan); the grid finds are one
  click away, and the URL keeps the choice (`#scope=all`).
- A link shared before this change opens in the award view; its filters still apply.
- The guide's contents and `score` values do not change because of this ADR.
