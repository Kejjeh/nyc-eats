"""The Seed import: only open, trusted, rated-4.2+ roster rows in the four boroughs.

The roster's `unresolved:` rows carry a place_id in a few cases (Masa -> Bar Masa);
importing them would publish another room's rating under an award's name.
"""
import sqlite3

import pytest

from nyceats.seed import read_roster, select


def _db(tmp_path, venues):
    p = tmp_path / "rw.sqlite"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE venues (venue_slug, name, address, lat, lng, borough, neighborhood, status, place_id, "
                "rating, user_ratings_total, resolution, rw_slug, top_honor_label)")
    con.execute("CREATE TABLE venue_awards (venue_slug, source, level, award, year)")
    con.executemany("INSERT INTO venues VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [v[:3] + (40.76, -73.98) + v[3:] for v in venues])
    con.execute("INSERT INTO venue_awards VALUES ('le-bern','michelin','3 stars',NULL,2025)")
    con.commit()
    con.close()
    return p


V = [
    ("le-bern", "Le Bernardin", "155 W 51st", "Manhattan", "Midtown", "open", "P1", 4.7, 5000,
     "google places: hand-verified place_id", None, "Three Michelin stars"),
    ("masa", "Masa", "10 Columbus", "Manhattan", None, "open", "P2", 4.2, 591, "unresolved: hand ruling", None, None),
    ("closed", "Gone", "x", "Brooklyn", None, "closed", "P3", 4.6, 100, "Restaurant Week participant", "gone", None),
    ("bx", "Bronx Spot", "x", "The Bronx", None, "open", "P4", 4.3, 80, "Restaurant Week participant", "bx", None),
    ("si", "SI Spot", "x", "Staten Island", None, "open", "P5", 4.8, 80, "Restaurant Week participant", "si", None),
    ("low", "Low", "x", "Queens", None, "open", "P6", 4.1, 80, "Restaurant Week participant", "low", None),
]


def test_select_keeps_only_trusted_open_rated_rows_in_scope(tmp_path):
    kept, skipped = select(read_roster(_db(tmp_path, V)))
    assert [k["place_id"] for k in kept] == ["P1", "P4"]
    assert skipped == {"no trusted place_id": 1, "not open": 1, "outside the four boroughs": 1,
                       "rated below 4.2": 1}


def test_the_bronx_is_normalised_and_awards_attach(tmp_path):
    kept = {k["place_id"]: k for k in select(read_roster(_db(tmp_path, V)))[0]}
    assert kept["P4"]["borough"] == "Bronx" and kept["P4"]["restaurant_week"] is True
    assert kept["P1"]["awards"][0]["level"] == "3 stars"


def test_two_rows_sharing_a_place_id_become_one_row_keeping_every_award(tmp_path):
    """25 place_ids in the real roster carry two open rows (Babbo / Babbo Ristorante e Enoteca)."""
    dup = V + [("le-bern-2", "Le Bernardin Prive", "x", "Manhattan", None, "open", "P1", 4.7, 50,
                "google places: name 1.00", "le-bern-2", None)]
    kept, skipped = select(read_roster(_db(tmp_path, dup)))
    row = next(k for k in kept if k["place_id"] == "P1")
    assert [k["place_id"] for k in kept] == ["P1", "P4"]
    assert row["name"] == "Le Bernardin"             # the most-awarded row names it
    assert row["also_listed_as"] == ["Le Bernardin Prive"]
    assert row["restaurant_week"] is True            # either row's RW flag carries over
    assert skipped["merged into another row with the same place_id"] == 1


def test_the_source_database_is_opened_read_only(tmp_path):
    p = _db(tmp_path, V)
    before = p.read_bytes()
    read_roster(p)
    assert p.read_bytes() == before
