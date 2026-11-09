"""The City spine: parsing DOHMH rows, the ZIP->borough map, and matching a Google place to a camis.

The rows below have the real shape of the grouped query (fetched 2026-11-09),
including the two quirks that matter: a missing coordinate is written as "0",
and one camis can come back twice when its fields changed between inspections.
"""
from nyceats.spine import SpineIndex, parse_rows, zip_boroughs

ROWS = [
    {"camis": "1", "dba": "LE BERNARDIN", "boro": "Manhattan", "building": "155", "street": "WEST 51 STREET",
     "zipcode": "10019", "phone": "2125541515", "cuisine_description": "French", "latitude": "40.7615",
     "longitude": "-73.9818", "nta": "MN17", "last_inspected": "2026-03-01T00:00:00.000"},
    # Same camis, older inspection, different phone: the newer row must win.
    {"camis": "1", "dba": "LE BERNARDIN", "boro": "Manhattan", "building": "155", "street": "WEST 51 STREET",
     "zipcode": "10019", "phone": "2120000000", "latitude": "0", "longitude": "0",
     "last_inspected": "2025-06-01T00:00:00.000"},
    {"camis": "2", "dba": "COBBLESTONE PUB (FOOD COURT)", "boro": "Queens", "building": "8", "street": "TERMINAL",
     "zipcode": "11430", "phone": "9293373183", "latitude": "0", "longitude": "0",
     "last_inspected": "2026-09-23T00:00:00.000"},
    {"camis": "3", "dba": "PIZZA PLACE", "boro": "Staten Island", "zipcode": "10301"},
    {"camis": "4", "dba": "SAMOS", "boro": "Queens", "building": "37-04", "street": "74 STREET",
     "zipcode": "11372", "phone": "7180000001", "nta": "QN28", "last_inspected": "2026-01-01T00:00:00.000"},
    {"camis": "5", "dba": "SAMOS 2", "boro": "Queens", "building": "40-01", "street": "74 STREET",
     "zipcode": "11372", "phone": "7180000002", "nta": "QN28", "last_inspected": "2026-01-01T00:00:00.000"},
]


def test_parse_keeps_one_row_per_camis_newest_wins_and_drops_staten_island():
    spine = parse_rows(ROWS)
    assert [s["camis"] for s in spine] == ["1", "2", "4", "5"]
    assert spine[0]["phone"] == "2125541515" and spine[0]["last_inspected"] == "2026-03-01"


def test_zero_coordinates_are_missing_not_the_atlantic():
    s = {r["camis"]: r for r in parse_rows(ROWS)}["2"]
    assert s["lat"] is None and s["lng"] is None


def test_zip_boroughs_and_unknown_zip():
    zb = zip_boroughs(parse_rows(ROWS))
    assert zb["10019"] == "Manhattan" and zb["11372"] == "Queens"
    assert "07030" not in zb  # Hoboken: not a borough, so the guide drops it


def test_match_by_phone():
    idx = SpineIndex(parse_rows(ROWS))
    rec, how = idx.match("Le Bernardin", "(212) 554-1515", "10019", "155 W 51st St, New York, NY 10019, USA")
    assert rec["camis"] == "1" and how == "phone"


def test_match_by_name_and_building_when_phone_differs():
    idx = SpineIndex(parse_rows(ROWS))
    rec, how = idx.match("Samos", "(718) 999-9999", "11372", "37-04 74th St, Jackson Heights, NY 11372, USA")
    assert rec["camis"] == "4" and how == "name+building"


def test_two_similar_names_at_other_buildings_is_a_miss_not_a_guess():
    idx = SpineIndex(parse_rows(ROWS))
    rec, why = idx.match("Samos", None, "11372", "99-99 74th St, Jackson Heights, NY 11372, USA")
    assert rec is None and "2 DOHMH records" in why


def test_shared_switchboard_phone_needs_a_similar_name():
    idx = SpineIndex(parse_rows(ROWS))
    rec, _ = idx.match("Totally Different Bistro", "(929) 337-3183", "11430", "1 Other Rd, Queens, NY 11430, USA")
    assert rec is None


def test_neighborhood_from_the_building_when_the_name_does_not_match():
    idx = SpineIndex(parse_rows(ROWS))
    assert idx.nta_at("11372", "37-04 74th St, Jackson Heights, NY 11372, USA") == "QN28"


def test_no_neighborhood_when_records_at_the_building_disagree():
    rows = ROWS + [{"camis": "9", "dba": "OTHER", "boro": "Queens", "building": "37-04", "street": "OTHER ST",
                    "zipcode": "11372", "nta": "QN99", "last_inspected": "2026-01-01T00:00:00.000"}]
    assert SpineIndex(parse_rows(rows)).nta_at("11372", "37-04 74th St, NY 11372") is None
