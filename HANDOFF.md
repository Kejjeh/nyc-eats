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
