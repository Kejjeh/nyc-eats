# Agent guide

## What this is

A public, static guide to the best sit-down restaurants in the Bronx, Manhattan, Brooklyn and Queens
(tasting menus, prix fixe, omakase, unusual proteins), rated 4.2+ and shown at 4.5+ by default. A Python
package (`nyceats/`) merges three sources into `docs/data/restaurants.json`, which `docs/index.html`
renders on GitHub Pages: the city's inspection data (free), the nyc-restaurants award roster (free,
read-only) and Google Places, grown only inside Google's monthly free allowance.
**Current state: working; site built from the roster only, first live discovery run awaits the owner's OK.**
Read `HANDOFF.md` for what's next and `GLOSSARY.md` for the terms. Decisions: `docs/adr/`.

## Commands (all verified from repo root, 2026-11-09, Windows, Python 3.13, node 24)

```bash
pip install -r requirements.txt                 # requests, pypdf, pytest, tzdata
python -m pytest tests -q                       # ~1s. Expect: 163 passed (node tests skip without node)
python -m nyceats spine                         # NETWORK, free: DOHMH + NTA names -> data/city/ (~15 s)
python -m nyceats seed                          # local, free: nyc-restaurants roster -> data/seed/rw_roster.json
python -m nyceats plan                          # offline: discovery plan vs this month's ledger
python -m nyceats discover -n 20                # dry run: prints what 20 calls would do, sends nothing
python -m nyceats discover --live -n 20         # add --pool details/themed/nearby to run one pool. BILLED SKUs, inside the free cap. Owner OK first, every time
python -m nyceats menus -n 50                   # free, network: read 50 restaurants' own sites -> data/menus.json
python -m nyceats monthly                       # free: spine + seed + dry run of every pool
python -m nyceats monthly --live                # the monthly refresh: every pool to its cap, menus, build (scheduled task)
python -m nyceats build                         # offline: -> docs/data/restaurants.json
python -m http.server 8771 --directory docs     # view the site; file:// does NOT work (fetch)
```

`spine` must have run once on a fresh clone: `data/city/dohmh.json` is gitignored (6.5 MB, regenerable).
Set `PYTHONUTF8=1` on Windows when printing names (macrons, accents).

## Architecture map

| File | Role |
|---|---|
| `nyceats/__main__.py` | CLI: spine, seed, plan, discover, build |
| `nyceats/spine.py` | City spine (DOHMH): one row per `camis`; ZIP→borough; `SpineIndex` matches a place to a camis |
| `nyceats/seed.py` | Seed: open, trusted, 4.2+ rows of the nyc-restaurants SQLite (opened `mode=ro`) |
| `nyceats/ledger.py` | Quota ledger: counts every Google call before it is sent; refuses past 950 per SKU per Pacific month |
| `nyceats/places_api.py` | Field masks, `sku_for` (bills at the highest field tier), `parse_place`, `Client` |
| `nyceats/plan.py` | Discovery plan: four pools (details, themed, nearby, fill), stable item ids, density grid |
| `nyceats/discover.py` | Dry run / live run; merges results into `data/places.json`; resumes from `data/discovery_state.json` |
| `nyceats/menus.py` | Menu crawl (ADR 0004): robots.txt, menu-link and PDF finder, evidence sentences + prices → `data/menus.json` |
| `nyceats/build.py` | Scope filter (`leave_out_reason`: review floor, dinner types, ADR 0005), category evidence (ADR 0003), neighborhoods, cuisine, awards, score → payload |
| `nyceats/names.py` | Name similarity (copied from omakase, threshold 0.80), phone, ZIP, building number |
| `docs/index.html`, `app.js` | The page (ported from nyc-restaurants `docs/venues.js`); opens on the award winners (ADR 0006) |
| `docs/core.js` | The page's pure logic; tested under node by `tests/test_site_core.py` |
| `docs/styles.css`, `venues.css`, `data/boroughs.json` | Copied unchanged from nyc-restaurants; `eats.css` adds ours |

## Conventions and gotchas

- **Restaurants are keyed by Google `place_id`.** The seed merges roster rows that share one (25 do, e.g.
  "Babbo" / "Babbo Ristorante e Enoteca") and lists the other names in `also_listed_as`.
- **Never hand-edit generated files:** `docs/data/restaurants.json`, `data/places.json`,
  `data/discovery_state.json`, `data/menus.json`, `data/history/*`, `data/seed/rw_roster.json`, `data/city/*`. Never lower a count in
  `data/quota_ledger.json`; code only adds to it.
- **Google costs money.** Only `discover --live` calls Google. Every request goes through `Client`, which
  reserves in the ledger first; there is no other path. Do not add one. Owner OK before every live run.
- **Borough comes from the ZIP** (City spine majority), not from the search rectangle; a ZIP not in the
  spine (NJ, Nassau) is out of scope. **Neighborhood comes from DOHMH `nta`** (ADR 0001), by phone or
  name+building match, else from same-building records when they all agree, else null.
- **Null means unknown.** Unknown hours are not "closed"; Open now says how many it could not judge.
- `build` refuses to shrink the payload by more than 20%; spine refresh refuses a 20% smaller city.
  Those guards catch upstream outages. Don't bypass them to "make it work".
- Frontend: bump `?v=N` on a changed `.js`/`.css` in `index.html`. No `innerHTML` for data; every href
  through `isHttpURL()`; facet counts via `matches(row, exceptKey)`.
- nyc-restaurants and omakase are **read-only** from here (owner rule). Code is shared by copying.
- **Do not read into context:** `docs/data/restaurants.json`, `data/places.json`, `data/city/dohmh.json`,
  `data/seed/rw_roster.json`, `docs/data/boroughs.json`. Use `python -c` one-liners.

## Before you finish any task

1. `python -m pytest tests -q` → `163 passed` (more if you added tests). CI runs the same on push and PR.
2. `python -m nyceats build` → exits 0; `restaurants` did not drop unless you meant it (9,588 on 2026-11-10,
   after the November fill searches); check `left_out` and `neighborhood_match` in the printed meta.
3. `git diff --stat` → only files you meant to change. A changed page file has its `?v=` bumped.

## Model routing

Safe for Sonnet: docs; page CSS/copy; adding tests; adding a theme to `plan.THEMES`; running spine, seed,
plan, build and dry runs. Escalate to Opus: anything in `ledger.py` or `places_api.sku_for` (money); the
score (`build.PRIOR`, the mean); `leave_out_reason` (the guide's scope); category evidence (ADR 0003); match logic in `spine.SpineIndex`;
anything contradicting an ADR. A live `discover` run needs the owner's OK whichever model runs it.

## Secrets

The Google key comes from env `GOOGLE_PLACES_KEY`, else `GOOGLE_API_KEY` in the gitignored `config.py`
(copy `config.example.py`), else the same name in omakase's gitignored `scripts/config.py` (read only;
the key every live run so far has used). Never commit, print or paste it; CI fails if one is tracked. The repo is public.
