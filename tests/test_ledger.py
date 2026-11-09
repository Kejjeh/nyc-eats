"""The ledger is the only thing standing between a bug and a Google bill.

Each test names a way the cap could be lifted by accident.
"""
from datetime import datetime, timezone

import pytest

from nyceats.ledger import CAP, Ledger, QuotaExhausted, billing_month

NOV = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def test_reserve_counts_and_persists(tmp_path):
    p = tmp_path / "ledger.json"
    Ledger(p).reserve("text_search_enterprise_atmosphere", 3, now=NOV)
    assert Ledger(p).used("text_search_enterprise_atmosphere", "2026-11") == 3


def test_cap_refuses_the_call_that_would_pass_it_and_counts_nothing(tmp_path):
    p = tmp_path / "ledger.json"
    led = Ledger(p)
    led.reserve("nearby_search_enterprise_atmosphere", CAP - 1, now=NOV)
    led.reserve("nearby_search_enterprise_atmosphere", 1, now=NOV)  # exactly at the cap is allowed
    with pytest.raises(QuotaExhausted):
        led.reserve("nearby_search_enterprise_atmosphere", 1, now=NOV)
    assert Ledger(p).used("nearby_search_enterprise_atmosphere", "2026-11") == CAP


def test_skus_have_separate_caps(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.reserve("text_search_enterprise", CAP, now=NOV)
    led.reserve("text_search_enterprise_atmosphere", 1, now=NOV)  # a different SKU is unaffected
    assert led.remaining("text_search_enterprise", "2026-11") == 0


def test_free_ids_only_search_is_counted_but_never_capped(tmp_path):
    led = Ledger(tmp_path / "l.json")
    led.reserve("text_search_essentials_ids", CAP + 10, now=NOV)
    assert led.remaining("text_search_essentials_ids") is None


def test_unknown_sku_is_refused_rather_than_left_uncapped(tmp_path):
    with pytest.raises(ValueError, match="unknown SKU"):
        Ledger(tmp_path / "l.json").reserve("text_search_entreprise", now=NOV)


def test_billing_month_is_pacific_time():
    # 03:00 UTC on Dec 1 is still Nov 30 in California, so it bills to November.
    assert billing_month(datetime(2026, 12, 1, 3, tzinfo=timezone.utc)) == "2026-11"
    assert billing_month(datetime(2026, 12, 1, 9, tzinfo=timezone.utc)) == "2026-12"


def test_naive_datetime_is_refused():
    with pytest.raises(ValueError):
        billing_month(datetime(2026, 11, 1))


def test_a_file_that_is_not_a_ledger_is_refused(tmp_path):
    p = tmp_path / "l.json"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a quota ledger"):
        Ledger(p)
