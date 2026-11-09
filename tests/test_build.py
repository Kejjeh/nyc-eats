"""The site payload: what is left out and why, cuisine labels, award badges, the score, and a full build.

`leave_out_reason` is the scope of the guide (ADR 0002) in code. Each case
below is a kind of place the probe actually returned.
"""
import pytest

from nyceats import build as B
from nyceats import paths
from nyceats.jsonio import write_json


@pytest.mark.parametrize("g,rating,borough,expected", [
    (None, 4.5, None, "outside the four boroughs (ZIP not in the City spine)"),
    ({"business_status": "CLOSED_PERMANENTLY"}, 4.8, "Bronx", "Google status CLOSED_PERMANENTLY"),
    ({"business_status": "OPERATIONAL"}, 4.1, "Queens", "rated below 4.2"),
    ({"primary_type": "coffee_shop", "types": ["coffee_shop", "restaurant"]}, 4.7, "Manhattan",
     "not sit-down (coffee_shop)"),
    ({"primary_type": "italian_restaurant", "dine_in": False}, 4.7, "Brooklyn", "no dine-in (Google)"),
    ({"primary_type": "night_club", "types": ["night_club"]}, 4.7, "Brooklyn", "not sit-down (night_club)"),
    ({"primary_type": "hotel", "types": ["hotel", "lodging"]}, 4.7, "Manhattan", "not a restaurant (hotel)"),
    ({"primary_type": "italian_restaurant", "types": ["restaurant"], "dine_in": None}, 4.2, "Bronx", None),
    (None, 4.6, "Manhattan", None),  # a roster row with no Google record yet stays in
])
def test_leave_out_reason(g, rating, borough, expected):
    assert B.leave_out_reason(g, rating, borough) == expected


def test_cuisine_prefers_a_specific_google_type_then_the_city_label():
    assert B.cuisine_of("italian_restaurant", "Pizza") == "Italian"
    assert B.cuisine_of("steak_house", None) == "Steakhouse"
    assert B.cuisine_of("restaurant", "Japanese") == "Japanese"
    assert B.cuisine_of("fine_dining_restaurant", "Bakery Products/Desserts") == "Bakery Products"
    assert B.cuisine_of(None, "Not Listed/Not Applicable") is None


def test_award_badges_keep_the_latest_year_and_a_fixed_order():
    awards = [{"source": "james_beard", "level": "nominee", "year": 2019},
              {"source": "michelin", "level": "1 star", "year": 2023},
              {"source": "michelin", "level": "1 star", "year": 2025},
              {"source": "unknown", "level": "x", "year": 2025}]
    assert B.award_badges(awards) == ["Michelin ★ 2025", "James Beard nominee 2019"]


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    for name in ("SPINE", "NTA_NAMES", "SEED", "PLACES", "SITE_DATA", "MENUS"):
        monkeypatch.setattr(paths, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(paths, "HISTORY", tmp_path / "history")
    write_json(paths.SPINE, [
        {"camis": "1", "name": "LE BERNARDIN", "borough": "Manhattan", "building": "155", "street": "W 51",
         "zip": "10019", "phone": "2125541515", "cuisine": "French", "nta": "MN17", "lat": None, "lng": None,
         "last_inspected": "2026-01-01"},
        {"camis": "2", "name": "X", "borough": "Bronx", "building": "1", "street": "A", "zip": "10458",
         "phone": None, "cuisine": "Italian", "nta": "BX06", "lat": None, "lng": None,
         "last_inspected": "2026-01-01"}])
    write_json(paths.NTA_NAMES, {"MN17": "Midtown-Midtown South", "BX06": "Belmont"})
    write_json(paths.SEED, [{"place_id": "LB", "name": "Le Bernardin", "address": "155 W. 51st St., Manhattan, NY, 10019",
                             "borough": "Manhattan", "rw_neighborhood": "Midtown", "rating": 4.7, "reviews": 5000,
                             "restaurant_week": False, "top_honor": None, "rw_slug": "le-bernardin",
                             "awards": [{"source": "michelin", "level": "3 stars", "year": 2025}]}])
    write_json(paths.PLACES, {
        "G1": {"place_id": "G1", "name": "Tiny Spot", "address": "9 A St, Bronx, NY 10458, USA", "rating": 5.0,
               "reviews": 3, "primary_type": "italian_restaurant", "types": ["restaurant"],
               "business_status": "OPERATIONAL", "found_by": ["themed:goat", "themed:tasting-menu"],
               "summary": "Roast goat and stews", "fetched_at": "2026-11-10T00:00:00Z"},
        "NJ": {"place_id": "NJ", "name": "Hoboken", "address": "1 Washington St, Hoboken, NJ 07030, USA",
               "rating": 4.9, "reviews": 900, "found_by": ["nearby"], "fetched_at": "2026-11-10T00:00:00Z"}})
    return tmp_path


def test_full_build(inputs):
    meta = B.build()
    payload = B.read_json(paths.SITE_DATA)
    rows = {r["id"]: r for r in payload["restaurants"]}
    assert set(rows) == {"LB", "G1"}
    assert meta["left_out"] == {"outside the four boroughs (ZIP not in the City spine)": 1}
    # "goat" is named, so that theme tags; nothing says tasting menu, so that one is counted, not tagged.
    assert meta["theme_matches_without_evidence"] == {"tasting-menu": 1}
    lb, g1 = rows["LB"], rows["G1"]
    assert lb["neighborhood"] == "Midtown-Midtown South" and lb["cuisine"] == "French"
    assert lb["awards"] == ["Michelin ★★★ 2025"] and lb["source"] == "roster"
    assert g1["borough"] == "Bronx" and g1["categories"] == ["Unusual proteins"] and g1["checked"] == "2026-11-10"
    # The score shrinks each rating toward the guide's mean by 150 reviews of doubt (RW's GOOGLE_PRIOR):
    # a 5.0 from 3 reviews keeps almost none of its lead over the mean; a 4.7 from 5,000 keeps nearly all.
    mean = payload["meta"]["rating_mean"]
    assert mean == 4.85
    assert g1["score"] == round((5.0 * 3 + mean * 150) / 153, 4)
    assert lb["score"] == round((4.7 * 5000 + mean * 150) / 5150, 4)
    assert [r["id"] for r in payload["restaurants"]] == sorted(rows, key=lambda i: -rows[i]["score"])


def test_build_refuses_to_publish_a_much_thinner_guide(inputs):
    write_json(paths.SITE_DATA, {"meta": {"restaurants": 100}, "restaurants": []})
    with pytest.raises(RuntimeError, match="shrink"):
        B.build()


def test_first_month_flags_nothing_then_the_next_month_compares(inputs, monkeypatch):
    monkeypatch.setattr(B, "billing_month", lambda: "2026-11")
    B.build()
    assert all(r["fresh"] is None for r in B.read_json(paths.SITE_DATA)["restaurants"])
    assert B.read_json(paths.HISTORY / "2026-11.json") == {"G1": [5.0, 3], "LB": [4.7, 5000]}
    # December: G1 gains 0.1 on 0 new reviews (not rising), LB is unchanged, and a new place appears.
    write_json(paths.HISTORY / "2026-11.json", {"G1": [4.9, 3], "LB": [4.6, 4980]})
    places = B.read_json(paths.PLACES)
    places["N1"] = dict(places["G1"], place_id="N1", name="Fresh Spot", found_by=["nearby"])
    write_json(paths.PLACES, places)
    monkeypatch.setattr(B, "billing_month", lambda: "2026-12")
    meta = B.build()
    fresh = {r["id"]: r["fresh"] for r in B.read_json(paths.SITE_DATA)["restaurants"]}
    assert fresh == {"G1": None, "LB": "Rising", "N1": "New to the guide"}
    assert meta["freshness"] == {"month": "2026-12", "compared_with": "2026-11", "New to the guide": 1, "Rising": 1}
