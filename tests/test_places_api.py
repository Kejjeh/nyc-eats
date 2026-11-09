"""The SKU a request bills at, and parsing what comes back.

A mask that bills higher than the ledger thinks would spend from the wrong
free allowance; a parser that assumes a field exists would drop a whole run
on the first place without a price level (Benoit, in the recon probe).
"""
import pytest

from nyceats.ledger import CAP, Ledger, QuotaExhausted
from nyceats.places_api import DETAIL_FIELDS, SEARCH_MASK, Client, parse_place, sku_for


def test_ids_only_text_search_is_the_free_sku():
    assert sku_for("text_search", "places.id") == "text_search_essentials_ids"


def test_one_atmosphere_field_lifts_the_whole_request():
    assert sku_for("text_search", "places.id,places.displayName,places.delivery") == "text_search_enterprise_atmosphere"


def test_the_guides_masks_bill_at_enterprise_atmosphere():
    assert sku_for("text_search", SEARCH_MASK + ",nextPageToken") == "text_search_enterprise_atmosphere"
    assert sku_for("nearby_search", SEARCH_MASK) == "nearby_search_enterprise_atmosphere"
    assert sku_for("place_details", DETAIL_FIELDS) == "place_details_enterprise_atmosphere"


def test_an_unknown_field_is_refused_rather_than_guessed_cheap():
    with pytest.raises(ValueError, match="no known SKU tier"):
        sku_for("text_search", "places.id,places.fancyNewField")


def test_parse_place_survives_missing_fields():
    rec = parse_place({"id": "abc"}, "2026-11-09T00:00:00Z")
    assert rec["place_id"] == "abc"
    assert rec["price_level"] is None and rec["delivery"] is None and rec["hours"] is None


def test_parse_place_maps_price_and_hours():
    rec = parse_place({
        "id": "x", "displayName": {"text": "Le Bernardin"}, "priceLevel": "PRICE_LEVEL_VERY_EXPENSIVE",
        "regularOpeningHours": {"periods": [{"open": {"day": 1, "hour": 17, "minute": 30},
                                             "close": {"day": 1, "hour": 22, "minute": 0}},
                                            {"open": {"day": 0, "hour": 0, "minute": 0}}],
                                "weekdayDescriptions": ["Monday: 5:30 – 10:00 PM"]},
    }, "t")
    assert rec["price_level"] == 4
    assert rec["hours"] == [[1, 17, 30, 1, 22, 0], [0, 0, 0, None, None, None]]


def test_parse_place_refuses_a_place_with_no_id():
    with pytest.raises(ValueError):
        parse_place({"displayName": {"text": "x"}}, "t")


class _Boom:
    """A session that fails the test if anything reaches the network."""
    def request(self, *a, **k):
        raise AssertionError("a request was sent past an exhausted ledger")


def test_client_sends_nothing_once_the_cap_is_reached(tmp_path):
    led = Ledger(tmp_path / "l.json", allow_new=True)
    led.reserve("place_details_enterprise_atmosphere", CAP)
    client = Client("k", led, session=_Boom(), pause=0)
    with pytest.raises(QuotaExhausted):
        client.details("ChIJ123")
    assert client.calls == 0
