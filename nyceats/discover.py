"""Run the Discovery plan against Google, inside the ledger, and merge what comes back into places.json.

Dry run is the default everywhere: `python -m nyceats discover -n N` prints what
N calls would do and sends nothing. `--live` is needed to spend from the free
allowance, and even then the ledger refuses any call past 950 for its SKU.
"""
from __future__ import annotations

import os
import time
from collections import Counter

from . import paths, spine
from .jsonio import read_json, write_json
from .ledger import Ledger, QuotaExhausted, billing_month
from .places_api import Client, PlacesError, now_iso, parse_place
from .plan import POOL_SKU, build_plan

POOLS = ("details", "themed", "nearby")


def load_inputs():
    return spine.load(), read_json(paths.SEED), read_json(paths.DISCOVERY_STATE, default={})


def pending(plan: list[dict], state: dict) -> list[dict]:
    return [it for it in plan if it["id"] not in state]


def schedule(plan: list[dict], state: dict, ledger: Ledger, max_calls: int | None,
             pool: str | None = None) -> list[dict]:
    """The items the next run would take: pools in order, each until its SKU's headroom runs out.

    A themed item can need up to 3 calls (pages), so it is only scheduled when
    3 calls of headroom remain; an item is never started that the cap would cut
    off mid-way, because a half-paged search cannot be resumed from its token.
    """
    budget = max_calls if max_calls is not None else 10**9
    room = {pool: ledger.remaining(POOL_SKU[pool]) for pool in POOLS}
    out = []
    for it in pending(plan, state):
        if pool and it["pool"] != pool:
            continue
        need = it["pages"]
        if need > budget or need > room[it["pool"]]:
            continue
        out.append(it)
        budget -= need
        room[it["pool"]] -= need
    return out


def dry_run(max_calls: int | None, ledger: Ledger | None = None, pool: str | None = None) -> str:
    ledger = ledger or Ledger(mirror=paths.LEDGER_MIRROR)
    sp, seed, state = load_inputs()
    plan = build_plan(sp, seed)
    todo = pending(plan, state)
    sched = schedule(plan, state, ledger, max_calls, pool)
    lines = [f"Billing month {billing_month()} (Pacific).",
             f"{'pool':8} {'SKU':38} {'used':>5} {'left':>5} {'items left':>10} {'calls (max)':>11} "
             f"{'this run':>8}"]
    for pool in POOLS:
        sku = POOL_SKU[pool]
        left_items = [i for i in todo if i["pool"] == pool]
        run = [i for i in sched if i["pool"] == pool]
        lines.append(f"{pool:8} {sku:38} {ledger.used(sku):>5} {ledger.remaining(sku):>5} "
                     f"{len(left_items):>10} {sum(i['pages'] for i in left_items):>11} "
                     f"{sum(i['pages'] for i in run):>8}")
    total = sum(i["pages"] for i in sched)
    lines.append(f"\nThis run: at most {total} calls, every one inside a free monthly allowance "
                 f"(cap 950 per SKU; Google's free tier is 1,000). Expected Google charge: $0.00.")
    by_b = Counter((i["pool"], i["borough"]) for i in sched)
    if sched:
        lines.append("By pool and borough: " + ", ".join(f"{p}/{b} {n}" for (p, b), n in sorted(by_b.items())))
        lines.append("First items: " + ", ".join(i["id"] for i in sched[:5]))
    return "\n".join(lines)


def merge(places: dict, rec: dict, tag: str) -> bool:
    """Fold a fresh record into places.json. Returns True when the place is new to the guide."""
    old = places.get(rec["place_id"])
    is_new = old is None
    merged = dict(rec)
    merged["found_by"] = sorted(set((old or {}).get("found_by", [])) | {tag})
    merged["first_seen"] = (old or {}).get("first_seen") or rec["fetched_at"]
    places[rec["place_id"]] = merged
    return is_new


def run_item(client: Client, it: dict, places: dict, now: str) -> dict:
    calls = new = results = 0
    if it["pool"] == "details":
        rec = parse_place(client.details(it["place_id"]), now)
        calls, results = 1, 1
        new += merge(places, rec, "seed")
    else:
        body = dict(it["body"])
        tag = f"themed:{it['theme']}" if it["pool"] == "themed" else "nearby"
        for page in range(it["pages"]):
            resp = client.text_search(body) if it["pool"] == "themed" else client.nearby_search(body)
            calls += 1
            for p in resp.get("places", []):
                results += 1
                new += merge(places, parse_place(p, now), tag)
            token = resp.get("nextPageToken")
            if it["pool"] != "themed" or not token:
                break
            body["pageToken"] = token
            time.sleep(2)  # Google needs a moment before a page token is valid (recon probe)
    return {"ran_at": now, "calls": calls, "results": results, "new": new}


# A details lookup Google answers with one of these is about that one place (an ID gone stale, a
# listing removed): record it and move on. Any other error (403 key, 429 quota, 5xx) would fail
# every item the same way, so it stops the run.
ITEM_ERRORS = {400, 404}


def run_live(max_calls: int, *, client: Client | None = None, ledger: Ledger | None = None,
             pool: str | None = None) -> dict:
    import requests

    from .keys import google_key
    with _RunLock(paths.RUN_LOCK):
        ledger = ledger or Ledger(mirror=paths.LEDGER_MIRROR)
        client = client or Client(google_key(), ledger)
        sp, seed, state = load_inputs()
        places = read_json(paths.PLACES, default={})
        sched = schedule(build_plan(sp, seed), state, ledger, max_calls, pool)
        summary = Counter()
        stopped = None
        for it in sched:
            try:
                out = run_item(client, it, places, now_iso())
            except QuotaExhausted as e:
                stopped = str(e)
            except PlacesError as e:
                if it["pool"] == "details" and e.status in ITEM_ERRORS:
                    out = {"ran_at": now_iso(), "calls": 1, "results": 0, "new": 0, "failed": str(e)[:200]}
                    summary["failed items"] += 1
                else:
                    stopped = str(e)
            except (requests.RequestException, ValueError) as e:
                stopped = f"{type(e).__name__}: {e}"
            if stopped:
                # Pages already fetched for a half-finished item stay in `places` and are saved; the
                # item itself is not marked done, so it runs again from page 1 next time.
                _save(places, state)
                break
            state[it["id"]] = out
            summary["items"] += 1
            summary["new places"] += out["new"]
            summary["results"] += out["results"]
            # Save after every item, so a crash loses at most one item's results, never the ledger's count.
            _save(places, state)
        return {"calls sent": client.calls, **summary, "places on file": len(places), "stopped early": stopped}


def _save(places: dict, state: dict) -> None:
    write_json(paths.PLACES, places, compact_rows=True)
    write_json(paths.DISCOVERY_STATE, state, compact_rows=True)


class _RunLock:
    """Refuse a second live run while one is going: two would overwrite each other's places.json."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SystemExit(f"{self.path} exists: another live discovery run is going. If none is "
                             "(a killed run left it), delete the file and run again.") from None
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        os.unlink(self.path)
