"""Build the site payload: Google records + Seed + City spine -> docs/data/restaurants.json.

Offline and deterministic apart from `generated_at`. Every row left out is
counted by reason in `meta.left_out`, so a filter that starts dropping too
much shows up in the build output instead of as a quietly thinner site.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from . import paths, spine
from .jsonio import read_json, write_json
from .ledger import billing_month
from .menus import current_evidence
from .names import zip_from_address
from .plan import EXCLUDED_PRIMARY, MIN_RATING, THEME_CATEGORY

# How many reviews of doubt a rating is shrunk by: the same m = 150 the nyc-restaurants
# pages use (its src/config.py GOOGLE_PRIOR), since this site is built from that page code.
PRIOR = 150
# Fewer reviews than this and a rating says too little to rank (owner ruling, issue #4 item 2:
# 170 places left the guide in November; none of them held an award).
MIN_REVIEWS = 20
# Primary types left out as not sit-down that come back when Google says the place seats diners
# for dinner (owner ruling, issue #4 item 3): Katz's, Mile End Deli, Terroir. Bars stay out even
# then (a cocktail bar or sports pub with food is not a dinner restaurant), and so does the rest
# of plan.EXCLUDED_PRIMARY. See ADR 0005.
DINNER_TYPES = {"deli", "sandwich_shop", "cafe", "wine_bar"}

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


# A themed search tags a restaurant only with evidence it fits (owner ruling, 2026-11-09). Google
# ranks by relevance and always fills the page: where a borough has few tasting menus it returns good
# restaurants nearby instead (the first live run's Bronx results), and tagging those would claim a meal
# they do not serve. Evidence is what Google returned: the place's type, a word in its name or
# editorial summary, or (for the expensive themes only) a $$$/$$$$ price. A menu crawl can add more later.
_TASTING = r"tasting|omakase|kaiseki|kappo|prix|fixe|multi-?course|chef'?s counter|set menu"
THEME_WORDS = {
    "tasting-menu": _TASTING, "kaiseki": _TASTING, "prix-fixe": _TASTING,
    # Whole words only where a fragment is common: "game" in "watch the game", "a5" in a name,
    # "counter" in "order at the counter" are not evidence (review of PR #1).
    "omakase": r"omakase|chef'?s counter|kappo|kaiseki",
    "chefs-counter": r"omakase|chef'?s counter|kappo|sushi counter|counter seat",
    "fine-dining": r"tasting|fine dining|michelin",
    "wagyu": r"wagyu|kobe|\ba5\b",
    "wild-game": r"venison|wild game|\bgame (?:bird|meat)|\bboar\b|\belk\b|bison|quail|pheasant",
    "goat": r"goat|chivo|cabrito|mutton", "rabbit": r"rabbit|conejo|lapin|coniglio",
    "eel": r"\beel|unagi|anago", "octopus": r"octopus|pulpo|polpo|tako",
    "uni": r"\buni\b|sea urchin|erizo", "peking-duck": r"peking|roast duck|duck",
}
# What the menu crawl (menus.MENU_WORDS) found on the restaurant's own site counts for the
# category it names. This is the evidence ADR 0003 asked for, and the strongest kind.
MENU_CATEGORY = {"tasting-menu": "Tasting menu", "prix-fixe": "Prix fixe",
                 "omakase": "Omakase & chef's counter", "chefs-counter": "Omakase & chef's counter"}
PRICE_EVIDENCE = {"tasting-menu": 3, "kaiseki": 3, "prix-fixe": 3, "omakase": 3, "chefs-counter": 3,
                  "fine-dining": 4}  # protein themes: price says nothing about the protein


def menu_evidence(category: str, menu: dict | None) -> str | None:
    """The sentence on the restaurant's own site that names this kind of meal, if the crawl read one."""
    for mt, snippet in current_evidence(menu).items():
        if MENU_CATEGORY.get(mt) == category:
            return snippet
    return None


def theme_evidence(theme: str, g: dict, menu: dict | None = None) -> str | None:
    """Why this place plausibly fits the theme it was found by, or None when nothing says so."""
    if theme not in THEME_WORDS:
        raise KeyError(f"theme {theme!r} has no evidence rule; add one to THEME_WORDS")
    if PRICE_EVIDENCE.get(theme) and g.get("primary_type") == "fine_dining_restaurant":
        return "Google type fine_dining_restaurant"
    text = f"{g.get('name') or ''} {g.get('summary') or ''}"
    m = re.search(THEME_WORDS[theme], text, re.I)
    if m:
        return f"name or summary mentions {m.group(0).lower()!r}"
    if theme in THEME_CATEGORY and menu_evidence(THEME_CATEGORY[theme], menu):
        return "restaurant's own site"
    floor = PRICE_EVIDENCE.get(theme)
    if floor and (g.get("price_level") or 0) >= floor:
        price = f"price {'$' * g['price_level']}"
        # Issue #4 item 5: where the restaurant's own site was read and names no such meal, price
        # alone is no longer evidence of one, except for fine dining, which $$$$ comes close to
        # defining. An unread site says nothing either way, so price still counts there.
        if THEME_CATEGORY.get(theme) == "Fine dining":
            return price
        if not (menu and menu.get("status") == "ok"):
            return f"{price}, own site not read"
    return None


def category_reasons(g: dict | None, dropped: list, menu: dict | None = None) -> dict[str, str]:
    """Category -> why it applies. Each theme match without evidence is appended to `dropped`.

    A category comes from a themed search plus evidence (ADR 0003), or from the restaurant's own
    site naming the meal outright (menu crawl), whether or not a search returned the place.
    """
    if not g:
        return {}
    why: dict[str, str] = {}
    if g.get("primary_type") == "fine_dining_restaurant":
        why["Fine dining"] = "Google type fine_dining_restaurant"
    for tag in g.get("found_by", []):
        if not tag.startswith("themed:"):
            continue
        theme = tag.split(":", 1)[1]
        reason = theme_evidence(theme, g, menu)
        if reason:
            why.setdefault(THEME_CATEGORY[theme], reason)
        else:
            dropped.append(theme)
    for cat in sorted(set(MENU_CATEGORY.values())):
        if cat not in why and menu_evidence(cat, menu):
            why[cat] = "restaurant's own site"
    return dict(sorted(why.items()))


def categories_for(g: dict | None, dropped: list, menu: dict | None = None) -> list[str]:
    """Categories with evidence, sorted. See category_reasons."""
    return list(category_reasons(g, dropped, menu))


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


# What's new (freshness flags). Each build saves this month's ratings to data/history/YYYY-MM.json;
# a row is compared with the latest earlier month. With no earlier month nothing is flagged, so the
# first month never calls the whole guide "new".
RISING_STARS = 0.1    # rating up by at least this much ...
RISING_REVIEWS = 10   # ... on at least this many new reviews


def freshness(rows: list[dict], previous: dict | None) -> dict[str, str]:
    """id -> "New to the guide" | "Rising", against the previous month's {id: [rating, reviews]}."""
    if not previous:
        return {}
    out = {}
    for r in rows:
        before = previous.get(r["id"])
        if before is None:
            out[r["id"]] = "New to the guide"
        elif (r["rating"] is not None and before[0] is not None and r["rating"] - before[0] >= RISING_STARS - 1e-9
              and (r["reviews"] or 0) - (before[1] or 0) >= RISING_REVIEWS):
            out[r["id"]] = "Rising"
    return out


def previous_month(history_dir, month: str) -> tuple[str | None, dict | None]:
    files = sorted(p for p in history_dir.glob("*.json") if p.stem < month) if history_dir.exists() else []
    return (files[-1].stem, read_json(files[-1])) if files else (None, None)


def leave_out_reason(g: dict | None, rating, borough, reviews) -> str | None:
    if borough is None:
        return "outside the four boroughs (ZIP not in the City spine)"
    if g and g.get("business_status") not in (None, "OPERATIONAL"):
        return f"Google status {g['business_status']}"
    if rating is None:
        return "no rating"
    if rating < MIN_RATING:
        return f"rated below {MIN_RATING}"
    if (reviews or 0) < MIN_REVIEWS:
        return f"fewer than {MIN_REVIEWS} reviews"
    if g and g.get("primary_type") in DINNER_TYPES and g.get("dine_in") is True and g.get("serves_dinner") is True:
        return None
    if g and g.get("primary_type") in EXCLUDED_PRIMARY:
        return f"not sit-down ({g['primary_type']})"
    if g and g.get("dine_in") is False:
        return "no dine-in (Google)"
    if g and g.get("primary_type") and "restaurant" not in (g.get("types") or []) \
            and not g["primary_type"].endswith("restaurant"):
        return f"not a restaurant ({g['primary_type']})"
    return None


def write_payload(path, meta: dict, rows: list[dict]) -> None:
    """The page's data file: readable meta, then one restaurant per line.

    Pretty-printing every field made 4,300 rows 8 MB and every data PR a wall of diff; one row
    per line is about half the size, and a moved restaurant is one changed line.
    """
    import json
    import os
    body = ('{"meta": ' + json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True)
            + ',\n"restaurants": [\n'
            + ",\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in rows)
            + "\n]}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def build(write: bool = True) -> dict:
    sp = spine.load()
    nta_names = read_json(paths.NTA_NAMES)
    seed = {s["place_id"]: s for s in read_json(paths.SEED)}
    places = read_json(paths.PLACES, default={})
    menus = read_json(paths.MENUS, default={})
    zb = spine.zip_boroughs(sp)
    index = spine.SpineIndex(sp)

    rows, left_out, matched, untagged = [], Counter(), Counter(), []
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
        reason = leave_out_reason(g, rating, borough, reviews)
        if reason:
            left_out[reason] += 1
            continue
        rec, how = index.match(name, (g or {}).get("phone"), zip_code, address)
        lat = (g or {}).get("lat") if g and g.get("lat") is not None else (s or {}).get("lat")
        lng = (g or {}).get("lng") if g and g.get("lng") is not None else (s or {}).get("lng")
        nta, where = (rec["nta"], "matched by " + how) if rec else (None, None)
        if not nta:
            nta = index.nta_at(zip_code, address)
            where = "neighborhood from same-building records" if nta else None
        if not nta:
            nta = index.nta_near(lat, lng)
            where = "neighborhood from records on the block" if nta else "no neighborhood"
        matched[where] += 1
        menu = menus.get(pid)
        why = category_reasons(g, untagged, menu)
        menu_ok = bool(menu and menu.get("status") == "ok")
        rows.append({
            "id": pid, "name": name, "address": address, "borough": borough, "zip": zip_code,
            "neighborhood": nta_names.get(nta) if nta else None, "nta": nta,
            "neighborhood_rw": (s or {}).get("rw_neighborhood"),
            "cuisine": cuisine_of((g or {}).get("primary_type"), rec["cuisine"] if rec else None),
            "rating": rating, "reviews": reviews,
            "price": (g or {}).get("price_level"),
            "categories": list(why), "category_why": why,
            "menu": {"checked": menu["checked"], "prices": menu.get("prices") or [],
                     "says": {MENU_CATEGORY[k]: v for k, v in current_evidence(menu).items()}}
            if menu_ok else None,
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
            "lat": lat, "lng": lng,
            # The city's letter grade, only for a restaurant matched to its own inspection record.
            "grade": {"letter": rec["grade"], "date": rec["grade_date"]} if rec and rec.get("grade") else None,
            "source": "google" if g else "roster",
            "checked": ((g or {}).get("fetched_at") or "")[:10] or None,
        })

    rated = [r["rating"] for r in rows if r["rating"] is not None]
    mean = round(sum(rated) / len(rated), 3) if rated else None
    for r in rows:
        n = r["reviews"] or 0
        r["score"] = round((r["rating"] * n + mean * PRIOR) / (n + PRIOR), 4)
    rows.sort(key=lambda r: (-r["score"], r["name"]))

    month = billing_month()
    prev_month, prev = previous_month(paths.HISTORY, month)
    fresh = freshness(rows, prev)
    for r in rows:
        r["fresh"] = fresh.get(r["id"])

    meta = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "restaurants": len(rows), "by_borough": dict(Counter(r["borough"] for r in rows)),
        "with_google_details": sum(1 for r in rows if r["source"] == "google"),
        "prior": PRIOR, "rating_mean": mean, "min_rating": MIN_RATING, "min_reviews": MIN_REVIEWS,
        "left_out": dict(left_out), "neighborhood_match": dict(matched),
        "theme_matches_without_evidence": dict(Counter(untagged)),
        "menus": {"read": sum(1 for r in rows if r["menu"]),
                  "categories_from_site": sum(1 for r in rows for w in r["category_why"].values()
                                              if w == "restaurant's own site"),
                  # Facts for the price ruling (ADR 0003 follow-up): tags still resting on price alone,
                  # split by whether the restaurant's site was read (and so did not name the meal).
                  "price_only": dict(Counter(
                      "site read, does not say" if r["menu"] else "site not read"
                      for r in rows for w in r["category_why"].values() if w.startswith("price")))},
        "freshness": {"month": month, "compared_with": prev_month, **Counter(fresh.values())},
        "graded": dict(Counter(r["grade"]["letter"] for r in rows if r["grade"])),
        "spine_restaurants": len(sp),
    }
    if write:
        old = read_json(paths.SITE_DATA, default={"meta": {"restaurants": 0}})
        if len(rows) < 0.8 * old["meta"]["restaurants"]:
            raise RuntimeError(f"payload would shrink from {old['meta']['restaurants']} to {len(rows)} rows; "
                               "refusing. Check the inputs before publishing a thinner guide.")
        write_payload(paths.SITE_DATA, meta, rows)
        write_json(paths.HISTORY / f"{month}.json", {r["id"]: [r["rating"], r["reviews"]] for r in rows},
                   compact_rows=True)
    return meta
