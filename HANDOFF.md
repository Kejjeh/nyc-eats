# Handoff

## State (2026-11-09)

Built: spine, seed, ledger, discovery (dry run tested; live path tested against a fake Google), build,
and the page. The payload holds the 977 roster rows only; **no Google call has been made by the
guide's code.** The ledger starts at the 29 recon-probe calls of 2026-11-09.

## Next

1. **Owner OK, then the first live run.** Suggested: a 30-call smoke run
   (`python -m nyceats discover --live -n 30`), `build`, eyeball the page, then the rest of November:
   947 details + 168 themed + 363 nearby calls, all inside the free tier. Expected charge $0.00.
2. Enable GitHub Pages (main, `/docs`) once the build PR is merged.
3. Monthly run (a scheduled task on this PC, owner to approve): spine, seed, `discover --live` up to the
   cap, build, commit. Pools refresh oldest-first once the plan is exhausted (not written yet).
4. Menu crawl to verify categories (tasting menu / prix fixe) on restaurant websites.
5. `recommend` CLI and an "ask Claude" box on the page (the chat-query goal).

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
