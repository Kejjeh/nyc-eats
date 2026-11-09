"""The Seed: the nyc-restaurants award roster (Michelin, Beard, NYT, Restaurant Week), imported for free.

Its place_ids were resolved and hand-reviewed there, so they are trusted here:
an `unresolved:` resolution is skipped, never re-guessed. The database is opened
read-only (`mode=ro`); nothing in nyc-restaurants is ever written (owner rule).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

from . import paths
from .jsonio import write_json

BOROUGH_NAMES = {"Manhattan": "Manhattan", "Brooklyn": "Brooklyn", "Queens": "Queens",
                 "The Bronx": "Bronx", "Bronx": "Bronx"}
MIN_RATING = 4.2  # ADR 0002: collect everything rated 4.2+


def read_roster(db_path: Path) -> list[dict]:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"nyc-restaurants database not found at {db_path}")
    con = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        venues = con.execute(
            "SELECT venue_slug, name, address, lat, lng, borough, neighborhood, status, place_id, rating, "
            "user_ratings_total, resolution, rw_slug, top_honor_label FROM venues").fetchall()
        awards: dict[str, list[dict]] = {}
        for a in con.execute("SELECT venue_slug, source, level, award, year FROM venue_awards "
                             "ORDER BY year DESC, source"):
            awards.setdefault(a["venue_slug"], []).append(
                {"source": a["source"], "level": a["level"], "award": a["award"], "year": a["year"]})
    finally:
        con.close()
    return [dict(v) | {"awards": awards.get(v["venue_slug"], [])} for v in venues]


def select(roster: list[dict]) -> tuple[list[dict], Counter]:
    """The roster rows in scope, and a count of why each other row was left out."""
    kept, skipped = [], Counter()
    for v in roster:
        borough = BOROUGH_NAMES.get(v["borough"] or "")
        reason = (
            "not open" if v["status"] != "open" else
            "no trusted place_id" if not v["place_id"] or (v["resolution"] or "").startswith("unresolved") else
            "outside the four boroughs" if borough is None else
            "no rating" if v["rating"] is None else
            f"rated below {MIN_RATING}" if v["rating"] < MIN_RATING else None)
        if reason:
            skipped[reason] += 1
            continue
        kept.append({
            "place_id": v["place_id"], "name": v["name"], "address": v["address"], "borough": borough,
            "lat": v.get("lat"), "lng": v.get("lng"),
            "rw_neighborhood": v["neighborhood"], "rating": v["rating"], "reviews": v["user_ratings_total"],
            "restaurant_week": bool(v["rw_slug"]), "top_honor": v["top_honor_label"], "awards": v["awards"],
            "rw_slug": v["venue_slug"],
        })
    return merge_shared_place_ids(kept, skipped), skipped


def merge_shared_place_ids(rows: list[dict], skipped: Counter) -> list[dict]:
    """One guide row per place_id. The roster sometimes lists one room under two award names.

    Measured 2026-11-09: 25 place_ids carry two open roster rows. Most are one
    restaurant named two ways ("Babbo" and "Babbo Ristorante e Enoteca"), but a
    few are two businesses that Google resolves to one listing ("Contra" and
    "Bar Contra"). Either way the Google listing, and so the rating, is one, so
    the guide keeps one row: the name of the most-awarded row, every award, and
    the other names in `also_listed_as` so the merge is visible on the page.
    """
    by_id: dict[str, list[dict]] = {}
    for r in rows:
        by_id.setdefault(r["place_id"], []).append(r)
    out = []
    for group in by_id.values():
        group.sort(key=lambda r: (-len(r["awards"]), not r["restaurant_week"], r["name"]))
        head = dict(group[0])
        if len(group) > 1:
            skipped["merged into another row with the same place_id"] += len(group) - 1
            head["also_listed_as"] = [r["name"] for r in group[1:]]
            head["awards"] = [a for r in group for a in r["awards"]]
            head["restaurant_week"] = any(r["restaurant_week"] for r in group)
            head["top_honor"] = next((r["top_honor"] for r in group if r["top_honor"]), None)
        out.append(head)
    return sorted(out, key=lambda k: k["place_id"])


def refresh(db_path: Path = paths.RW_DB) -> dict:
    kept, skipped = select(read_roster(db_path))
    write_json(paths.SEED, kept, compact_rows=True)
    return {"seeded": len(kept), "by_borough": dict(Counter(k["borough"] for k in kept)),
            "skipped": dict(skipped)}
