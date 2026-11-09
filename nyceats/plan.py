"""The Discovery plan: every Google call the guide intends to make, as stable, resumable items.

Three Pools, one per Places SKU, each with its own 950-a-month cap (ADR 0002):

- **details**  Place Details (Enterprise + Atmosphere) for each Seed row, best-rated
               first. The seed has ratings but no hours, website, price or delivery.
- **themed**   Text Search (Enterprise + Atmosphere) for the owner's priorities in
               each borough: tasting menus, prix fixe, omakase and chef's counters,
               fine dining, unusual proteins. Up to 3 pages of 20, rated 4.2+.
- **nearby**   Nearby Search (Enterprise + Atmosphere) on a grid laid over the city's
               own restaurant density (the City spine), 20 most popular per circle.

An item's id never changes, so a run that stops at the cap resumes next month
where it left off.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .spine import BOROUGHS

POOL_SKU = {"details": "place_details_enterprise_atmosphere",
            "themed": "text_search_enterprise_atmosphere",
            "nearby": "nearby_search_enterprise_atmosphere"}

# (slug, query text, category shown on the site)
THEMES = [
    ("tasting-menu", "tasting menu restaurant", "Tasting menu"),
    ("kaiseki", "kaiseki", "Tasting menu"),
    ("prix-fixe", "prix fixe dinner", "Prix fixe"),
    ("omakase", "omakase", "Omakase & chef's counter"),
    ("chefs-counter", "chef's counter", "Omakase & chef's counter"),
    ("fine-dining", "fine dining restaurant", "Fine dining"),
    ("wagyu", "wagyu", "Unusual proteins"),
    ("wild-game", "wild game venison restaurant", "Unusual proteins"),
    ("goat", "goat dishes restaurant", "Unusual proteins"),
    ("rabbit", "rabbit dish restaurant", "Unusual proteins"),
    ("eel", "eel unagi restaurant", "Unusual proteins"),
    ("octopus", "octopus restaurant", "Unusual proteins"),
    ("uni", "sea urchin uni", "Unusual proteins"),
    ("peking-duck", "peking duck", "Unusual proteins"),
]
THEME_CATEGORY = {slug: cat for slug, _, cat in THEMES}
MAX_PAGES = 3
MIN_RATING = 4.2

# Search rectangles. They overlap at the edges and spill into New Jersey and Nassau;
# that is fine, because the borough of each result comes from its ZIP, not from the rectangle.
RECTANGLES = {
    "Bronx": ((40.785, -73.935), (40.917, -73.765)),
    "Manhattan": ((40.700, -74.020), (40.880, -73.905)),
    "Brooklyn": ((40.570, -74.045), (40.740, -73.855)),
    "Queens": ((40.540, -73.965), (40.800, -73.700)),
}
# The Bronx is home (owner, 2026-11-09), so it goes first in every round-robin.
BOROUGH_ORDER = ("Bronx", "Manhattan", "Brooklyn", "Queens")
assert set(BOROUGH_ORDER) == set(BOROUGHS)

# Not sit-down restaurants (ADR 0002 scope). Also sent to Nearby Search as excludedPrimaryTypes.
EXCLUDED_PRIMARY = ["fast_food_restaurant", "cafe", "coffee_shop", "bakery", "ice_cream_shop", "dessert_shop",
                    "meal_takeaway", "sandwich_shop", "juice_shop", "donut_shop", "bagel_shop", "deli",
                    "food_court", "convenience_store", "grocery_store", "bar", "pub", "night_club",
                    "liquor_store", "tea_house", "chocolate_shop", "candy_store", "confectionery"]

M_PER_DEG_LAT = 111_000.0
START_SIDE_M = 3_200.0
SPLIT_ABOVE = 150   # restaurants in a cell: Nearby returns 20, so a busier cell is split
MIN_SIDE_M = 400.0
MIN_IN_CELL = 8     # a cell with fewer inspected restaurants is park, water or industry


def themed_items() -> list[dict]:
    items = []
    for slug, query, _ in THEMES:
        for b in BOROUGH_ORDER:
            (lo_lat, lo_lng), (hi_lat, hi_lng) = RECTANGLES[b]
            items.append({"id": f"themed:{slug}:{b.lower()}", "pool": "themed", "theme": slug, "borough": b,
                          "pages": MAX_PAGES, "body": {
                              "textQuery": query, "pageSize": 20, "minRating": MIN_RATING,
                              "locationRestriction": {"rectangle": {
                                  "low": {"latitude": lo_lat, "longitude": lo_lng},
                                  "high": {"latitude": hi_lat, "longitude": hi_lng}}}}})
    return items


def grid_cells(spine: list[dict]) -> list[dict]:
    """Quadtree over each borough's inspected restaurants: split any cell too busy for one 20-result call."""
    cells = []
    for b in BOROUGH_ORDER:
        pts = [(s["lat"], s["lng"]) for s in spine if s["borough"] == b and s["lat"] and s["lng"]]
        if not pts:
            continue
        lat0 = min(p[0] for p in pts)
        lng0 = min(p[1] for p in pts)
        m_per_deg_lng = M_PER_DEG_LAT * math.cos(math.radians(40.75))
        start = defaultdict(list)
        for lat, lng in pts:
            y = (lat - lat0) * M_PER_DEG_LAT
            x = (lng - lng0) * m_per_deg_lng
            start[(int(x // START_SIDE_M), int(y // START_SIDE_M))].append((x, y))
        stack = [(i * START_SIDE_M, j * START_SIDE_M, START_SIDE_M, p) for (i, j), p in start.items()]
        while stack:
            x0, y0, side, p = stack.pop()
            if len(p) > SPLIT_ABOVE and side / 2 >= MIN_SIDE_M:
                half = side / 2
                quads = defaultdict(list)
                for x, y in p:
                    quads[(x >= x0 + half, y >= y0 + half)].append((x, y))
                stack += [(x0 + half * qx, y0 + half * qy, half, q) for (qx, qy), q in quads.items()]
            elif len(p) >= MIN_IN_CELL:
                cx, cy = x0 + side / 2, y0 + side / 2
                cells.append({"borough": b, "n": len(p), "side_m": side,
                              "lat": round(lat0 + cy / M_PER_DEG_LAT, 5),
                              "lng": round(lng0 + cx / m_per_deg_lng, 5),
                              "radius_m": round(side * math.sqrt(2) / 2 + 50)})
    return cells


def nearby_items(spine: list[dict]) -> list[dict]:
    """Busiest cells first, boroughs taken in turn (Bronx first), so an early stop is still city-wide."""
    by_b = defaultdict(list)
    for c in grid_cells(spine):
        by_b[c["borough"]].append(c)
    for b in by_b:
        by_b[b].sort(key=lambda c: (-c["n"], c["lat"], c["lng"]))
    ordered = []
    while any(by_b.values()):
        for b in BOROUGH_ORDER:
            if by_b.get(b):
                ordered.append(by_b[b].pop(0))
    return [{"id": f"nearby:{c['lat']:.5f},{c['lng']:.5f},{c['radius_m']}", "pool": "nearby",
             "borough": c["borough"], "spine_restaurants": c["n"], "pages": 1, "body": {
                 "includedTypes": ["restaurant"], "excludedPrimaryTypes": EXCLUDED_PRIMARY,
                 "maxResultCount": 20, "rankPreference": "POPULARITY",
                 "locationRestriction": {"circle": {"center": {"latitude": c["lat"], "longitude": c["lng"]},
                                                    "radius": float(c["radius_m"])}}}}
            for c in ordered]


def details_items(seed: list[dict]) -> list[dict]:
    rows = sorted(seed, key=lambda s: (-(s["rating"] or 0), -(s["reviews"] or 0), s["place_id"]))
    return [{"id": f"details:{s['place_id']}", "pool": "details", "place_id": s["place_id"],
             "borough": s["borough"], "pages": 1} for s in rows]


def build_plan(spine: list[dict], seed: list[dict]) -> list[dict]:
    return details_items(seed) + themed_items() + nearby_items(spine)
