"""Build the site payload: Google records + Seed + City spine -> docs/data/restaurants.json.

Offline and deterministic apart from `generated_at`. Every row left out is
counted by reason in `meta.left_out`, so a filter that starts dropping too
much shows up in the build output instead of as a quietly thinner site.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from . import paths, spine
from .jsonio import read_json, write_json
from .names import zip_from_address
from .plan import EXCLUDED_PRIMARY, MIN_RATING, THEME_CATEGORY

# How many reviews of doubt a rating is shrunk by: the same m = 150 the nyc-restaurants
# pages use (its src/config.py GOOGLE_PRIOR), since this site is built from that page code.
PRIOR = 150

AWARD_LABELS = {
    ("michelin", "3 stars"): "Michelin ★★★", ("michelin", "2 stars"): "Michelin ★★",
    ("michelin", "1 star"): "Michelin ★", ("michelin", "bib_gourmand"): "Bib Gourmand",
    ("michelin", "recommended"): "Michelin recommended",
    ("james_beard", "winner"): "James Beard winner", ("james_beard", "nominee"): "James Beard nominee",
    ("james_beard", "semifinalist"): "James Beard semifinalist",
    ("nyt", "nyt_100_best"): "NYT 100 Best", ("nyt", "nyt_starred_review"): "NYT starred review",
}
# Primary types that say nothing about the cuisine; the DOHMH cuisine is used instead.
GENERIC_TYPES = {None, "restaurant", "fine_dining_restaurant", "bar_and_grill", "food", "point_of_interest",
                 "establishment", "bar", "wine_bar", "cocktail_bar", "brunch_restaurant", "lunch_restaurant",
                 "dinner_restaurant", "diner", "gastropub", "fusion_restaurant", "buffet_restaurant"}
TYPE_LABELS = {"steak_house": "Steakhouse", "barbecue_restaurant": "Barbecue", "sushi_restaurant": "Sushi",
               "ramen_restaurant": "Ramen", "seafood_restaurant": "Seafood", "pizza_restaurant": "Pizza",
               "vegan_restaurant": "Vegan", "vegetarian_restaurant": "Vegetarian",
               "middle_eastern_restaurant": "Middle Eastern", "korean_barbecue_restaurant": "Korean barbecue",
               "hot_pot_restaurant": "Hot pot", "dim_sum_restaurant": "Dim sum", "tapas_restaurant": "Tapas"}


def cuisine_of(primary_type: str | None, spine_cuisine: str | None) -> str | None:
    if primary_type not in GENERIC_TYPES:
        if primary_type in TYPE_LABELS:
            return TYPE_LABELS[primary_type]
        if primary_type.endswith("_restaurant"):
            return primary_type.removesuffix("_restaurant").replace("_", " ").title()
    if spine_cuisine and spine_cuisine not in ("Other", "Not Listed/Not Applicable"):
        return spine_cuisine.split("/")[0].strip()
    return None


def award_badges(awards: list[dict]) -> list[str]:
    """Distinct award labels, latest year shown: 'Michelin ★ 2025'."""
    latest: dict[str, int | None] = {}
    for a in awards:
        label = AWARD_LABELS.get((a["source"], a["level"]))
        if label and (latest.get(label) or 0) <= (a["year"] or 0):
            latest[label] = a["year"]
    order = list(AWARD_LABELS.values())
    return [f"{lab} {yr}" if yr else lab for lab, yr in sorted(latest.items(), key=lambda kv: order.index(kv[0]))]


def leave_out_reason(g: dict | None, rating, borough) -> str | None:
    if borough is None:
        return "outside the four boroughs (ZIP not in the City spine)"
    if g and g.get("business_status") not in (None, "OPERATIONAL"):
        return f"Google status {g['business_status']}"
    if rating is None:
        return "no rating"
    if rating < MIN_RATING:
        return f"rated below {MIN_RATING}"
    if g and g.get("primary_type") in EXCLUDED_PRIMARY:
        return f"not sit-down ({g['primary_type']})"
    if g and g.get("dine_in") is False:
        return "no dine-in (Google)"
    if g and g.get("primary_type") and "restaurant" not in (g.get("types") or []) \
            and not g["primary_type"].endswith("restaurant"):
        return f"not a restaurant ({g['primary_type']})"
    return None


def build(write: bool = True) -> dict:
    sp = spine.load()
    nta_names = read_json(paths.NTA_NAMES)
    seed = {s["place_id"]: s for s in read_json(paths.SEED)}
    places = read_json(paths.PLACES, default={})
    zb = spine.zip_boroughs(sp)
    index = spine.SpineIndex(sp)

    rows, left_out, matched = [], Counter(), Counter()
    for pid in sorted(set(seed) | set(places)):
        g, s = places.get(pid), seed.get(pid)
        name = (g or {}).get("name") or (s or {}).get("name")
        address = (g or {}).get("address") or (s or {}).get("address")
        if not name:
            left_out["no name"] += 1
            continue
        rating = (g or {}).get("rating") if g and g.get("rating") is not None else (s or {}).get("rating")
        reviews = (g or {}).get("reviews") if g and g.get("reviews") is not None else (s or {}).get("reviews")
        zip_code = zip_from_address(address)
        borough = zb.get(zip_code) or (s or {}).get("borough")
        reason = leave_out_reason(g, rating, borough)
        if reason:
            left_out[reason] += 1
            continue
        rec, how = index.match(name, (g or {}).get("phone"), zip_code, address)
        nta = rec["nta"] if rec else index.nta_at(zip_code, address)
        matched["matched by " + how if rec else
                "neighborhood from same-building records" if nta else "no neighborhood"] += 1
        categories = sorted({THEME_CATEGORY[t.split(":", 1)[1]] for t in (g or {}).get("found_by", [])
                             if t.startswith("themed:")}
                            | ({"Fine dining"} if (g or {}).get("primary_type") == "fine_dining_restaurant" else set()))
        rows.append({
            "id": pid, "name": name, "address": address, "borough": borough, "zip": zip_code,
            "neighborhood": nta_names.get(nta) if nta else None, "nta": nta,
            "neighborhood_rw": (s or {}).get("rw_neighborhood"),
            "cuisine": cuisine_of((g or {}).get("primary_type"), rec["cuisine"] if rec else None),
            "rating": rating, "reviews": reviews,
            "price": (g or {}).get("price_level"),
            "categories": categories,
            "awards": award_badges((s or {}).get("awards", [])),
            "restaurant_week": bool((s or {}).get("restaurant_week")),
            "also_listed_as": (s or {}).get("also_listed_as"),
            "website": (g or {}).get("website"), "maps_url": (g or {}).get("maps_url")
            or f"https://www.google.com/maps/place/?q=place_id:{pid}",
            "phone": (g or {}).get("phone"),
            "hours": (g or {}).get("hours"), "hours_text": (g or {}).get("hours_text"),
            "delivery": (g or {}).get("delivery"), "takeout": (g or {}).get("takeout"),
            "reservable": (g or {}).get("reservable"),
            "summary": (g or {}).get("summary"),
            "lat": (g or {}).get("lat") if g and g.get("lat") is not None else (s or {}).get("lat"),
            "lng": (g or {}).get("lng") if g and g.get("lng") is not None else (s or {}).get("lng"),
            "source": "google" if g else "roster",
            "checked": ((g or {}).get("fetched_at") or "")[:10] or None,
        })

    rated = [r["rating"] for r in rows if r["rating"] is not None]
    mean = round(sum(rated) / len(rated), 3) if rated else None
    for r in rows:
        n = r["reviews"] or 0
        r["score"] = round((r["rating"] * n + mean * PRIOR) / (n + PRIOR), 4)
    rows.sort(key=lambda r: (-r["score"], r["name"]))

    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "restaurants": len(rows), "by_borough": dict(Counter(r["borough"] for r in rows)),
        "with_google_details": sum(1 for r in rows if r["source"] == "google"),
        "prior": PRIOR, "rating_mean": mean, "min_rating": MIN_RATING,
        "left_out": dict(left_out), "neighborhood_match": dict(matched),
        "spine_restaurants": len(sp),
    }
    if write:
        old = read_json(paths.SITE_DATA, default={"meta": {"restaurants": 0}})
        if len(rows) < 0.8 * old["meta"]["restaurants"]:
            raise RuntimeError(f"payload would shrink from {old['meta']['restaurants']} to {len(rows)} rows; "
                               "refusing. Check the inputs before publishing a thinner guide.")
        write_json(paths.SITE_DATA, {"meta": meta, "restaurants": rows}, compact_rows=False)
    return meta
