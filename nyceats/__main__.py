"""python -m nyceats <command>. Run from the repo root.

  spine                   refresh the City spine from DOHMH + NTA names (free, network)
  seed                    import the nyc-restaurants award roster (free, local, read-only)
  plan                    show the discovery plan and what this month's ledger allows (free, offline)
  discover --live -n N [--pool P]   run up to N Google calls from the plan (BILLED SKUs; inside the free cap)
  menus [-n N] [--all] [--upgrade]
                          read restaurants' own websites for tasting/omakase/prix-fixe evidence (free, network);
                          --upgrade re-reads sites read before the crawl read PDF menus
  monthly [--live]        spine, seed, every pool up to the cap, menus, build. Dry without --live
  build                   merge everything into docs/data/restaurants.json (offline)
"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nyceats", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spine")
    sub.add_parser("seed")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("-n", "--max-calls", type=int, default=None)
    p_disc = sub.add_parser("discover")
    p_disc.add_argument("--live", action="store_true", help="actually call Google (otherwise a dry run)")
    p_disc.add_argument("-n", "--max-calls", type=int, required=True, help="hard ceiling on calls this run")
    p_disc.add_argument("--pool", choices=("details", "themed", "nearby"), help="only this pool")
    p_menu = sub.add_parser("menus")
    p_menu.add_argument("-n", "--limit", type=int, default=None, help="read at most N sites this run")
    p_menu.add_argument("--all", action="store_true", help="re-read every site, not only new or stale ones")
    p_menu.add_argument("--upgrade", action="store_true", help="re-read sites read before PDF menus were read")
    p_month = sub.add_parser("monthly")
    p_month.add_argument("--live", action="store_true", help="spend this month's free Google allowance")
    sub.add_parser("build")
    a = ap.parse_args(argv)

    if a.cmd == "spine":
        from .spine import refresh
        print(json.dumps(refresh(), indent=1))
    elif a.cmd == "seed":
        from .seed import refresh
        print(json.dumps(refresh(), indent=1))
    elif a.cmd == "plan":
        from .discover import dry_run
        print(dry_run(a.max_calls))
    elif a.cmd == "discover":
        from .discover import dry_run, run_live
        if not a.live:
            print(dry_run(a.max_calls, pool=a.pool))
            print("\nDry run: nothing was sent. Add --live to call Google.")
        else:
            print(json.dumps(run_live(a.max_calls, pool=a.pool), indent=1))
    elif a.cmd == "menus":
        from .menus import crawl
        print(json.dumps(crawl(a.limit, everything=a.all, upgrade=a.upgrade), indent=1))
    elif a.cmd == "monthly":
        print(json.dumps(monthly(a.live), indent=1))
    elif a.cmd == "build":
        from .build import build
        print(json.dumps(build(), indent=1))
    return 0


def monthly(live: bool) -> dict:
    """The monthly refresh: free inputs first, then Google up to each pool's cap, then menus, then build.

    Each pool runs to the ledger's cap (950 per SKU) and no further; the ledger refuses the rest.
    Without `live` it only prints the dry run, so a scheduled task can be checked by hand first.
    """
    from .build import build
    from .discover import POOLS, dry_run, run_live
    from .menus import crawl
    from .seed import refresh as seed_refresh
    from .spine import refresh as spine_refresh
    out = {"spine": spine_refresh(), "seed": seed_refresh()}
    if not live:
        out["dry_run"] = dry_run(None)
        return out
    out["discover"] = {pool: run_live(10**6, pool=pool) for pool in POOLS}
    # Build first so the crawl reads only places in the guide, then build again with what it found.
    build()
    out["menus"] = crawl()
    out["build"] = build()
    return out


if __name__ == "__main__":
    sys.exit(main())
