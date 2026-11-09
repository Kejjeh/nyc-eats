"""python -m nyceats <command>. Run from the repo root.

  spine                   refresh the City spine from DOHMH + NTA names (free, network)
  seed                    import the nyc-restaurants award roster (free, local, read-only)
  plan                    show the discovery plan and what this month's ledger allows (free, offline)
  discover --live -n N [--pool P]   run up to N Google calls from the plan (BILLED SKUs; inside the free cap)
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
    elif a.cmd == "build":
        from .build import build
        print(json.dumps(build(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
