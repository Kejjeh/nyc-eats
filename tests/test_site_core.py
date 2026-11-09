"""The page's pure logic (docs/core.js), run under the `node` on PATH. Skipped without node.

Open-now is the one place a bug silently hides good restaurants: a late-night
place whose hours cross midnight, or Saturday night into Sunday, must read as
open, and unknown hours must read as unknown rather than closed.
"""
import json
import shutil
import subprocess

import pytest

from nyceats import paths

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run(expr: str):
    core = (paths.ROOT / "docs" / "core.js").read_text(encoding="utf-8")
    script = core + f"\nprocess.stdout.write(JSON.stringify((() => {{ const E = globalThis.EATS; return {expr}; }})()));"
    # Script on stdin and UTF-8 both ways: a Windows command line would mangle the ★ in award names.
    out = subprocess.run([NODE, "-"], input=script, capture_output=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


MON_DINNER = [[1, 17, 30, 1, 22, 0]]
FRI_LATE = [[5, 18, 0, 6, 2, 0]]          # Friday 6 PM to Saturday 2 AM
SAT_LATE = [[6, 18, 0, 0, 1, 0]]          # Saturday 6 PM to Sunday 1 AM: wraps the week


@pytest.mark.parametrize("hours,day,minute,expected", [
    (MON_DINNER, 1, 18 * 60, True),
    (MON_DINNER, 1, 22 * 60, False),        # the close minute itself is closed
    (MON_DINNER, 2, 18 * 60, False),
    (FRI_LATE, 6, 60, True),                # 1 AM Saturday, still Friday's service
    (SAT_LATE, 0, 30, True),                # 12:30 AM Sunday, Saturday's service
    (SAT_LATE, 0, 90, False),
    ([[0, 0, 0, None, None, None]], 3, 700, True),  # open 24 hours
    (None, 1, 600, None),                   # unknown hours: unknown, not closed
    ([], 1, 600, None),
])
def test_is_open_at(hours, day, minute, expected):
    assert run(f"E.isOpenAt({json.dumps(hours)}, {day}, {minute})") == expected


def test_nyc_now_is_new_york_time_whatever_the_machine_zone():
    # 2026-11-10 03:30 UTC is Monday 22:30 in New York (EST, UTC-5).
    assert run("E.nycNow(new Date('2026-11-10T03:30:00Z'))") == {"day": 1, "minute": 22 * 60 + 30}


def test_weighted_rating_matches_the_build():
    assert round(run("E.weightedRating(5.0, 3, 150, 4.85)"), 4) == round((5.0 * 3 + 4.85 * 150) / 153, 4)
    assert run("E.weightedRating(null, 10, 150, 4.5)") is None


def test_distance_and_price_and_links():
    # Grand Central to Arthur Avenue, about 7.3 miles as the crow flies.
    assert 7.0 < run("E.distanceMi(40.7527, -73.9772, 40.8551, -73.8876)") < 8.5
    assert run("E.distanceMi(null, 1, 2, 3)") is None
    assert run("[E.priceLabel(null), E.priceLabel(0), E.priceLabel(3)]") == [None, "Free", "$$$"]
    urls = run("E.deliveryLinks('Café & Co').map(l => l.url)")
    assert all("Caf%C3%A9%20%26%20Co" in u for u in urls)


def test_href_guard_refuses_script_and_relative_urls():
    assert run("[E.isHttpURL('https://x.com'), E.isHttpURL('javascript:alert(1)'), E.isHttpURL('www.x.com')]") \
        == [True, False, False]


def test_award_kind_drops_the_year():
    assert run("E.awardKind('Michelin ★★ 2025')") == "Michelin ★★"


VOCAB = {"boroughs": ["Bronx", "Brooklyn", "Manhattan", "Queens"],
         "neighborhoods": ["Belmont", "Upper East Side-Carnegie Hill", "Hudson Yards-Chelsea-Flatiron-Union Square",
                           "East Village", "Park Slope-Gowanus"],
         "cuisines": ["Italian", "Thai", "Steakhouse", "Korean", "Japanese", "Pizza"],
         "awards": ["Michelin ★", "Michelin ★★", "Bib Gourmand", "Michelin recommended", "James Beard winner",
                    "NYT 100 Best"]}


def ask(text):
    return run(f"E.parseAsk({json.dumps(text)}, {json.dumps(VOCAB)})")


def test_ask_the_example_from_the_brief():
    a = ask("Italian, $$, open past 10, near Union Square")
    assert a["filters"] == {"price": ["$$"], "cuisine": ["Italian"]}
    assert a["openAt"] == 22 * 60 and a["near"] == "union square" and a["ignored"] == []


def test_ask_places_categories_awards_and_rating():
    a = ask("cheap thai in the Bronx with delivery rated 4.6+")
    assert a["filters"] == {"offers": ["Delivery"], "price": ["$", "$$"], "borough": ["Bronx"], "cuisine": ["Thai"]}
    assert a["minRating"] == 4.6
    a = ask("michelin starred tasting menu in Park Slope")
    assert a["filters"] == {"category": ["Tasting menu"], "award": ["Michelin ★", "Michelin ★★", "Michelin ★★★"],
                            "neighborhood": ["Park Slope-Gowanus"]}
    assert ask("any michelin steakhouses")["filters"] == {
        "award": ["Michelin ★", "Michelin ★★", "Michelin recommended"], "cuisine": ["Steakhouse"]}


def test_ask_neighborhood_parts_and_longest_name_first():
    assert ask("korean in the east village")["filters"] == {"neighborhood": ["East Village"], "cuisine": ["Korean"]}
    assert ask("upper east side omakase")["filters"] == {
        "category": ["Omakase & chef's counter"], "neighborhood": ["Upper East Side-Carnegie Hill"]}


@pytest.mark.parametrize("text,minute", [("open late", 23 * 60), ("open until 2", 120), ("open at 11:30pm", 23 * 60 + 30),
                                         ("open past 9 pm", 21 * 60), ("lunch at 12pm", 12 * 60)])
def test_ask_open_times(text, minute):
    assert ask(text)["openAt"] == minute


def test_ask_reports_what_it_could_not_place_instead_of_searching_for_it():
    a = ask("romantic italian with a view")
    assert a["filters"] == {"cuisine": ["Italian"]} and a["ignored"] == ["romantic", "view"]
    assert ask("open now")["openNow"] is True
