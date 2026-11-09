# Handoff

## State (2026-11-09)

**Live at https://kejjeh.github.io/nyc-eats/** (GitHub Pages, main `/docs`), since 2026-11-09.
Code: PR #1. Data from the first live run: PR #2. The payload holds 1,016 restaurants, 97 with Google
details; 82 are tagged "Tasting menu". The ledger holds the 29 recon-probe calls plus the 7 live calls.

## Next

1. **Next live run (needs the owner's OK each time).** The first (2026-11-09) was 7 themed
   "tasting menu" calls, 99 places. Left in November: 947 details + 159 themed + 368 nearby calls,
   all inside the free tier ($0.00). Each run's outputs go in a data-only PR, apart from code.
2. Monthly run (a scheduled task on this PC, owner to approve): spine, seed, `discover --live` up to the
   cap, build, commit. Pools refresh oldest-first once the plan is exhausted (not written yet).
3. Menu crawl to verify categories on restaurant websites. Priority: about half of the 53 tasting-menu tags that rest on price alone look wrong (ADR 0003 follow-up).
4. `recommend` CLI and an "ask Claude" box on the page (the chat-query goal).

## Open owner decisions

- **Score.** Uses nyc-restaurants' m = 150 shrinkage toward the mean of the 4.2+ guide (4.516 today).
  The README had said "Omakase's review-count adjustment" (Wilson lower bound with a 0.97 Google
  correction). Both shrink thin samples; they rank differently. Owner to pick.
- **Minimum reviews.** None today: a 5.0 from 3 reviews is in scope (and sorts near the mean).
- **Shared place_ids in the roster.** 25 place_ids carry two roster rows in nyc-restaurants; most are
  one room named twice, a few are two businesses (Contra / Bar Contra). Merged here; the source fix
  belongs to nyc-restaurants.

## Known limits

- **The ledger sees only this repo's calls.** Google's free allowance is per billing account. ADR 0002
  assumes omakase and nyc-restaurants use legacy Places SKUs that don't share these caps; that is not
  verified. Both are idle until late January (Restaurant Week), so November–January are unaffected.
  Check Google Cloud billing (SKU report) after the first live month, and before RW resumes.
- **Ledger safety (review 2026-11-09):** a live run holds `data/discover.lock`; every reservation
  re-reads the ledger under `data/quota_ledger.lock`; a copy at `~/.nyceats/quota_ledger.json` wins if
  the repo copy is ever rolled back. A killed run can leave a lock file: delete it only when no run is going.
- Roster rows with no Google record skip the closed-status and restaurant-type checks until their
  details lookup runs (first in the plan, best-rated first).
