"""The plan and the runner: what gets scheduled against the cap, and how results merge.

No test here touches the network. The fake client stands in for Google and
still goes through a real ledger, so the cap is exercised exactly as live.
"""
import pytest

from nyceats import discover, paths
from nyceats.ledger import CAP, Ledger
from nyceats.places_api import Client, sku_for
from nyceats.plan import POOL_SKU, THEMES, build_plan, grid_cells, themed_items

SPINE = [{"borough": "Bronx", "lat": 40.85 + i * 1e-4, "lng": -73.88, "zip": "10458"} for i in range(30)] + \
        [{"borough": "Manhattan", "lat": 40.75 + (i % 20) * 1e-4, "lng": -73.98 + (i // 20) * 1e-4, "zip": "10019"}
         for i in range(400)]
SEED = [{"place_id": f"P{i}", "rating": 4.5 + i / 100, "reviews": 100, "borough": "Manhattan"} for i in range(3)]


def test_every_pool_bills_the_sku_its_cap_is_kept_on():
    from nyceats.places_api import DETAIL_FIELDS, SEARCH_MASK
    assert POOL_SKU["details"] == sku_for("place_details", DETAIL_FIELDS)
    assert POOL_SKU["themed"] == sku_for("text_search", SEARCH_MASK + ",nextPageToken")
    assert POOL_SKU["nearby"] == sku_for("nearby_search", SEARCH_MASK)
    assert POOL_SKU["fill"] == sku_for("text_search", SEARCH_MASK + ",nextPageToken")


def test_themed_items_cover_every_theme_in_every_borough_bronx_first():
    items = themed_items()
    assert len(items) == len(THEMES) * 4
    assert items[0]["borough"] == "Bronx"
    assert all(i["body"]["minRating"] == 4.0 for i in items)  # the 0.5 step below 4.2: see the minRating tests


def test_busy_cells_are_split_and_empty_ones_dropped():
    cells = grid_cells(SPINE)
    assert sum(c["n"] for c in cells) == 430
    assert all(c["n"] <= 150 or c["side_m"] < 800 for c in cells)


def test_item_ids_are_stable_between_builds():
    assert [i["id"] for i in build_plan(SPINE, SEED)] == [i["id"] for i in build_plan(SPINE, SEED)]


def test_details_go_best_rated_first():
    ids = [i["place_id"] for i in build_plan(SPINE, SEED) if i["pool"] == "details"]
    assert ids == ["P2", "P1", "P0"]


def test_schedule_never_starts_a_themed_item_the_cap_would_cut_off(tmp_path):
    led = Ledger(tmp_path / "l.json", allow_new=True)
    led.reserve(POOL_SKU["themed"], CAP - 2)  # 2 calls left; a themed item can need 3
    plan = build_plan(SPINE, SEED)
    sched = discover.schedule(plan, {}, led, None)
    assert not [i for i in sched if i["pool"] == "themed"]
    assert len([i for i in sched if i["pool"] == "details"]) == 3


def test_schedule_respects_the_run_ceiling(tmp_path):
    sched = discover.schedule(build_plan(SPINE, SEED), {}, Ledger(tmp_path / "l.json", allow_new=True), 4)
    assert sum(i["pages"] for i in sched) <= 4


def test_done_items_are_not_scheduled_again(tmp_path):
    plan = build_plan(SPINE, SEED)
    state = {"details:P2": {"ran_at": "x"}}
    sched = discover.schedule(plan, state, Ledger(tmp_path / "l.json", allow_new=True), 1)
    assert sched[0]["id"] == "details:P1"


def test_merge_keeps_first_seen_and_unions_tags():
    places = {}
    assert discover.merge(places, {"place_id": "A", "fetched_at": "t1"}, "nearby") is True
    assert discover.merge(places, {"place_id": "A", "fetched_at": "t2", "rating": 4.6}, "themed:omakase") is False
    assert places["A"]["first_seen"] == "t1" and places["A"]["fetched_at"] == "t2"
    assert places["A"]["found_by"] == ["nearby", "themed:omakase"]


class FakeResp:
    def __init__(self, body):
        self.status_code, self._b, self.text = 200, body, ""

    def json(self):
        return self._b


class FakeSession:
    """Answers like Google: two pages for a text search, then no token."""
    def __init__(self):
        self.sent = []

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.sent.append((url, json))
        if "searchText" in url:
            page = 2 if json and json.get("pageToken") else 1
            return FakeResp({"places": [{"id": f"T{page}", "rating": 4.6}],
                             **({"nextPageToken": "tok"} if page == 1 else {})})
        if "searchNearby" in url:
            return FakeResp({"places": [{"id": "N1", "rating": 4.4}]})
        return FakeResp({"id": url.rsplit("/", 1)[-1], "rating": 4.7})


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("PLACES", "DISCOVERY_STATE", "LEDGER", "LEDGER_MIRROR", "RUN_LOCK"):
        monkeypatch.setattr(paths, name, tmp_path / f"{name}.json")
    # No test may reach the real key on this machine: a run_live without a fake client fails loudly.
    import nyceats.keys
    monkeypatch.setattr(nyceats.keys, "google_key", lambda: pytest.fail("a test asked for the real Google key"))
    monkeypatch.setattr(discover, "load_inputs", lambda: (SPINE, SEED, discover.read_json(
        paths.DISCOVERY_STATE, default={})))
    monkeypatch.setattr(discover.time, "sleep", lambda s: None)
    return tmp_path


def test_live_run_counts_every_call_in_the_ledger_and_resumes(sandbox):
    led = Ledger(paths.LEDGER, allow_new=True)
    session = FakeSession()
    # 6 = 3 details + one themed item reserved at 3 pages; Google stops after 2, so 5 are sent.
    out = discover.run_live(6, client=Client("k", led, session=session, pause=0), ledger=led)
    assert out["calls sent"] == len(session.sent) == 5
    assert session.sent[4][1]["pageToken"] == "tok"  # page 2 asked with the token page 1 gave
    assert led.used(POOL_SKU["details"]) == 3 and led.used(POOL_SKU["themed"]) == 2
    places = discover.read_json(paths.PLACES)
    assert set(places) == {"P0", "P1", "P2", "T1", "T2"}
    # A second run picks up after the finished items rather than repeating them.
    session2 = FakeSession()
    discover.run_live(2, client=Client("k", Ledger(paths.LEDGER, allow_new=True), session=session2, pause=0),
                      ledger=Ledger(paths.LEDGER, allow_new=True))
    assert not any("places/P" in url for url, _ in session2.sent)


def test_pool_option_schedules_only_that_pool(tmp_path):
    sched = discover.schedule(build_plan(SPINE, SEED), {}, Ledger(tmp_path / "l.json", allow_new=True), 10, pool="nearby")
    assert sched and all(i["pool"] == "nearby" for i in sched)


class StaleIdSession(FakeSession):
    """Google answers 404 for one stale place_id and normally for the rest."""
    def request(self, method, url, json=None, headers=None, timeout=None):
        if url.endswith("/P2"):
            self.sent.append((url, json))
            r = FakeResp({"error": {"code": 404}})
            r.status_code, r.text = 404, "NOT_FOUND"
            return r
        return super().request(method, url, json, headers, timeout)


def test_a_stale_place_id_is_recorded_and_the_run_moves_on(sandbox):
    led = Ledger(paths.LEDGER, allow_new=True)
    out = discover.run_live(3, client=Client("k", led, session=StaleIdSession(), pause=0), ledger=led)
    state = discover.read_json(paths.DISCOVERY_STATE)
    assert out["failed items"] == 1 and out["stopped early"] is None
    assert "404" in state["details:P2"]["failed"] and "details:P0" in state


class DownSession(FakeSession):
    """Page 1 of a text search works, then Google returns 500."""
    def request(self, method, url, json=None, headers=None, timeout=None):
        if "searchText" in url and json and json.get("pageToken"):
            self.sent.append((url, json))
            r = FakeResp({})
            r.status_code, r.text = 500, "backend error"
            return r
        return super().request(method, url, json, headers, timeout)


def test_a_server_error_stops_the_run_but_keeps_pages_already_paid_for(sandbox):
    led = Ledger(paths.LEDGER, allow_new=True)
    out = discover.run_live(6, client=Client("k", led, session=DownSession(), pause=0), ledger=led)
    assert "500" in out["stopped early"]
    assert "T1" in discover.read_json(paths.PLACES)  # page 1 survives
    assert not any(k.startswith("themed:") for k in discover.read_json(paths.DISCOVERY_STATE))  # item reruns


def test_a_second_live_run_is_refused_while_one_holds_the_lock(sandbox):
    paths.RUN_LOCK.write_text("1", encoding="utf-8")
    with pytest.raises(SystemExit, match="another live discovery run"):
        discover.run_live(1, client=Client("k", Ledger(paths.LEDGER, allow_new=True), session=FakeSession(), pause=0))


def test_nearby_ids_do_not_move_when_the_spine_grows():
    from nyceats.plan import nearby_items
    before = {i["id"] for i in nearby_items(SPINE)}
    far = [{"borough": "Bronx", "lat": 40.80, "lng": -73.92, "zip": "10454"} for _ in range(10)]
    after = {i["id"] for i in nearby_items(SPINE + far)}
    assert before <= after


def test_stale_items_come_after_new_ones_oldest_first_and_failures_are_not_retried():
    from datetime import datetime, timezone
    from nyceats.discover import due
    plan = [{"id": i, "pool": "details", "pages": 1} for i in ("a", "b", "c", "d", "e")]
    state = {"a": {"ran_at": "2026-10-20T00:00:00Z"}, "b": {"ran_at": "2026-10-01T00:00:00Z"},
             "c": {"ran_at": "2026-11-08T00:00:00Z"},
             "d": {"ran_at": "2026-09-01T00:00:00Z", "failed": "404"}}
    now = datetime(2026, 12, 1, tzinfo=timezone.utc)
    # e never ran; b and a are 28+ days old (b older); c is recent; d failed and stays failed.
    assert [it["id"] for it in due(plan, state, now)] == ["e", "b", "a"]


def test_a_full_nearby_search_is_split_into_quarters_and_a_full_quarter_again():
    from nyceats.plan import split_items
    base = [i for i in build_plan(SPINE, SEED) if i["pool"] == "nearby"]
    parent = base[0]
    assert split_items(base, {parent["id"]: {"results": 12, "ran_at": "x"}}) == []
    quarters = split_items(base, {parent["id"]: {"results": 20, "ran_at": "x"}})
    assert len(quarters) == 4 and {q["split_from"] for q in quarters} == {parent["id"]}
    r = parent["body"]["locationRestriction"]["circle"]["radius"]
    assert all(q["body"]["locationRestriction"]["circle"]["radius"] < r for q in quarters)
    assert all(q["body"]["includedTypes"] == ["restaurant"] for q in quarters)
    # Stable ids: the same state gives the same quarters, so a finished quarter is never bought twice.
    assert [q["id"] for q in quarters] == [q["id"] for q in split_items(base, {parent["id"]: {"results": 20}})]
    state = {parent["id"]: {"results": 20}, quarters[0]["id"]: {"results": 20}}
    second = split_items(base, state)
    assert len(second) == 8 and sum(1 for q in second if q.get("split_from") == quarters[0]["id"]) == 4
    # A failed search is not split.
    assert split_items(base, {parent["id"]: {"results": 20, "failed": "404"}}) == []


def nearby_and_quarters(state):
    from nyceats.plan import split_items
    base = [i for i in build_plan(SPINE, SEED) if i["pool"] == "nearby"]
    return base, split_items(base, state)


def test_a_fill_search_covers_each_full_square_whose_quarters_have_not_run():
    from nyceats.plan import SEARCH_MIN_RATING, fill_items
    base, _ = nearby_and_quarters({})
    parent = base[0]
    assert fill_items(base, {parent["id"]: {"results": 12}}) == []  # not full: Nearby saw everything
    state = {parent["id"]: {"results": 20, "new": 9}}
    base, quarters = nearby_and_quarters(state)
    fills = fill_items(base + quarters, state)
    assert len(fills) == 1 and fills[0]["square_of"] == parent["id"] and fills[0]["pool"] == "fill"
    body = fills[0]["body"]
    assert body["minRating"] == SEARCH_MIN_RATING and body["includedType"] == "restaurant" and body["pageSize"] == 20
    # The rectangle is the nearby circle's square: centred on it, inside the circle.
    c = parent["body"]["locationRestriction"]["circle"]
    rect = body["locationRestriction"]["rectangle"]
    lat = (rect["low"]["latitude"] + rect["high"]["latitude"]) / 2
    lng = (rect["low"]["longitude"] + rect["high"]["longitude"]) / 2
    assert abs(lat - c["center"]["latitude"]) < 1e-4 and abs(lng - c["center"]["longitude"]) < 1e-4
    half_m = (rect["high"]["latitude"] - rect["low"]["latitude"]) / 2 * 111_000
    assert half_m * 2 ** 0.5 < c["radius"]
    # Once a quarter has run, Nearby is working through that square, so no fill search for it.
    state[quarters[0]["id"]] = {"results": 7}
    assert fill_items(base + quarters, state) == []


def test_fill_searches_go_bronx_first_and_richest_square_first():
    from nyceats.plan import fill_items
    base, _ = nearby_and_quarters({})
    bronx = [i for i in base if i["borough"] == "Bronx"]
    manhattan = [i for i in base if i["borough"] == "Manhattan"]
    state = {manhattan[0]["id"]: {"results": 20, "new": 15}, bronx[0]["id"]: {"results": 20, "new": 3}}
    if len(manhattan) > 1:
        state[manhattan[1]["id"]] = {"results": 20, "new": 18}
    base, quarters = nearby_and_quarters(state)
    order = [(f["borough"], state[f["square_of"]]["new"]) for f in fill_items(base + quarters, state)]
    assert order[0] == ("Bronx", 3)
    assert [n for b, n in order if b == "Manhattan"] == sorted([n for b, n in order if b == "Manhattan"], reverse=True)


class FillSession:
    """Text search pages of 20; page 1 all new, page 2 all already known, page 3 never reached."""
    def __init__(self, known=()):
        self.sent, self.known = [], set(known)

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.sent.append((url, json))
        page = int((json or {}).get("pageToken") or 1)
        ids = [f"F{page}-{i}" for i in range(20)] if page == 1 else sorted(self.known)[:20]
        return FakeResp({"places": [{"id": i, "rating": 4.5} for i in ids], "nextPageToken": str(page + 1)})


def test_a_fill_search_pages_on_only_while_pages_are_full_and_mostly_new(sandbox):
    from nyceats.plan import fill_items
    base, _ = nearby_and_quarters({})
    state = {base[0]["id"]: {"results": 20, "new": 9, "ran_at": "2026-11-09T00:00:00Z"}}
    base, quarters = nearby_and_quarters(state)
    item = fill_items(base + quarters, state)[0]
    known = {f"K{i}": {"place_id": f"K{i}", "found_by": ["nearby"], "first_seen": "x"} for i in range(20)}
    places = dict(known)
    led = Ledger(paths.LEDGER, allow_new=True)
    session = FillSession(known)
    out = discover.run_item(Client("k", led, session=session, pause=0), item, places, "2026-11-10T00:00:00Z")
    # Page 1: 20 new, so page 2 is worth a call; page 2: nothing new, so no page 3.
    assert out["calls"] == 2 and out["pages_new"] == [20, 0] and out["new"] == 20
    assert led.used(POOL_SKU["fill"]) == 2
    assert all("fill" in places[f"F1-{i}"]["found_by"] for i in range(20))


def test_text_searches_ask_for_a_rating_google_does_not_round_up():
    # Google takes minRating in steps of 0.5 and rounds up: 4.2 behaved as 4.5. Of 938 text-search
    # results to 2026-11-10 none was below 4.5, while 2,741 of the guide's 6,433 rows are 4.2-4.49.
    # So searches ask for the step at or below the guide's floor, and the build keeps the 4.2 cut.
    from nyceats.plan import MIN_RATING, SEARCH_MIN_RATING, fill_items
    assert SEARCH_MIN_RATING * 2 == int(SEARCH_MIN_RATING * 2)
    assert MIN_RATING - 0.5 < SEARCH_MIN_RATING <= MIN_RATING
    state = {}
    base, _ = nearby_and_quarters(state)
    state[base[0]["id"]] = {"results": 20, "new": 9}
    base, quarters = nearby_and_quarters(state)
    text = themed_items() + fill_items(base + quarters, state)
    assert text and {it["body"]["minRating"] for it in text} == {SEARCH_MIN_RATING}


def test_a_text_search_run_with_another_min_rating_counts_as_never_run():
    from datetime import datetime, timezone
    from nyceats.discover import due
    from nyceats.plan import SEARCH_MIN_RATING
    plan = [{"id": i, "pool": p, "pages": 3 if p != "details" else 1, "body": {"minRating": SEARCH_MIN_RATING}}
            for i, p in (("t-old", "themed"), ("t-ok", "themed"), ("t-none", "themed"), ("n", "nearby"))]
    plan[-1]["body"] = {}
    ran = "2026-11-09T00:00:00Z"
    state = {"t-old": {"ran_at": ran, "min_rating": 4.2}, "t-ok": {"ran_at": ran, "min_rating": SEARCH_MIN_RATING},
             "t-none": {"ran_at": ran}, "n": {"ran_at": ran}}
    # Run with the filter that rounded to 4.5 (or before the filter was recorded): its 4.2-4.49
    # places were never asked for, so it is due now, in plan order, ahead of anything stale.
    assert [it["id"] for it in due(plan, state, datetime(2026, 11, 10, tzinfo=timezone.utc))] == ["t-old", "t-none"]


def test_a_text_search_records_the_min_rating_it_ran_with(sandbox):
    from nyceats.plan import SEARCH_MIN_RATING
    item = themed_items()[0]
    session = FillSession()
    out = discover.run_item(Client("k", Ledger(paths.LEDGER, allow_new=True), session=session, pause=0),
                            item, {}, "2026-11-10T00:00:00Z")
    assert out["min_rating"] == SEARCH_MIN_RATING
    assert all(body["minRating"] == SEARCH_MIN_RATING for _, body in session.sent)
