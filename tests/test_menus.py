"""Menu crawl: read restaurants' own sites without trusting a site that could not be read."""
from urllib.robotparser import RobotFileParser

from nyceats import menus
from nyceats.build import category_reasons, theme_evidence

HOME = """<html><head><title>Kono</title><script>var menu = "tasting menu";</script></head>
<body><nav><a href="/menu">Menu</a> <a href="https://www.kono.nyc/reservations">Book</a>
<a href="/menus/dinner.pdf">Dinner PDF</a> <a href="https://resy.com/kono">Resy</a>
<a href="/about">Our story</a> <a href="mailto:hi@kono.nyc">Email</a></nav>
<p>Kono is a yakitori counter in Chinatown.</p></body></html>"""
MENU = """<html><body><h2>Dinner</h2><p>Our 14-course chicken tasting menu is $165 per person.
Wine pairing $95.</p><p>Seats at the counter only.</p></body></html>"""


def test_script_text_is_not_page_text():
    text, links = menus.parse_html(HOME)
    assert "tasting menu" not in text and "yakitori counter" in text
    assert ("/menu", "Menu") in links


def test_menu_links_stay_on_the_site_and_skip_pdfs():
    _, links = menus.parse_html(HOME)
    assert menus.menu_links("https://kono.nyc/", links) == ["https://kono.nyc/menu"]


def test_evidence_and_prices_come_from_the_same_sentence():
    text, _ = menus.parse_html(MENU)
    ev, prices = menus.find_evidence(text)
    assert set(ev) == {"tasting-menu"}  # "at the counter" alone is not chef's-counter evidence
    assert "14-course chicken tasting menu" in ev["tasting-menu"]
    assert prices == ["$165"]  # the $95 pairing is in another sentence


def test_a_loose_word_on_a_long_page_is_not_evidence():
    ev, _ = menus.find_evidence("Lunch special. Game day deals. Sit at the counter. Fixed prices on drinks.")
    assert ev == {}


class FakeFetcher:
    def __init__(self, pages, robots_txt=""):
        self.pages, self.robots_txt, self.seen = pages, robots_txt, []

    def robots(self, url):
        rp = RobotFileParser()
        rp.parse(self.robots_txt.splitlines())
        return rp

    def get(self, url):
        self.seen.append(url)
        return (self.pages[url], "ok") if url in self.pages else (None, "http 404")


def test_check_site_reads_the_home_page_and_its_menu(monkeypatch):
    monkeypatch.setattr(menus.time, "sleep", lambda s: None)
    f = FakeFetcher({"https://kono.nyc/": HOME, "https://kono.nyc/menu": MENU * 3})
    rec = menus.check_site("https://kono.nyc/", f)
    assert rec["status"] == "ok" and rec["pages"] == ["https://kono.nyc/", "https://kono.nyc/menu"]
    assert rec["prices"] == ["$165"]


def test_robots_disallow_means_not_checked():
    f = FakeFetcher({"https://kono.nyc/": HOME}, robots_txt="User-agent: *\nDisallow: /")
    rec = menus.check_site("https://kono.nyc/", f)
    assert rec["status"] == "robots" and f.seen == []


def test_unreadable_site_keeps_its_reason():
    assert menus.check_site("https://gone.example/", FakeFetcher({}))["status"] == "http 404"


def test_a_javascript_only_site_is_not_read_as_empty():
    rec = menus.check_site("https://spa.example/", FakeFetcher({"https://spa.example/": "<div id=root></div>"}))
    assert rec["status"] == "no text" and rec["evidence"] == {}


def test_due_reads_new_changed_and_stale_sites_only():
    places = {"a": {"website": "https://a.nyc"}, "b": {"website": "https://b.nyc"},
              "c": {"website": "https://c-new.nyc"}, "d": {"website": None}, "e": {"website": "https://e.nyc"}}
    old = {"b": {"site": "https://b.nyc", "checked": "2026-11-01"},
           "c": {"site": "https://c-old.nyc", "checked": "2026-11-08"},
           "e": {"site": "https://e.nyc", "checked": "2026-09-01"}}
    assert [p for p, _ in menus.due(places, old, "2026-11-09")] == ["a", "c", "e"]


def ok_menu(**evidence):
    return {"status": "ok", "checked": "2026-11-09", "evidence": evidence, "prices": []}


def test_site_evidence_confirms_a_theme_before_price():
    g = {"name": "Rosella", "primary_type": "sushi_restaurant", "price_level": 3, "summary": None,
         "found_by": ["themed:tasting-menu"]}
    assert theme_evidence("tasting-menu", g).startswith("price")
    assert theme_evidence("tasting-menu", g, ok_menu(**{"tasting-menu": "Chef's tasting $120"})) \
        == "restaurant's own site"


def test_a_site_that_names_the_meal_tags_it_without_a_search():
    g = {"name": "Kono", "primary_type": "yakitori_restaurant", "found_by": ["details"]}
    assert category_reasons(g, [], ok_menu(**{"omakase": "Omakase only"})) == \
        {"Omakase & chef's counter": "restaurant's own site"}


def test_an_unread_site_is_not_evidence():
    g = {"name": "Kono", "primary_type": "yakitori_restaurant", "found_by": ["details"]}
    bad = {"status": "robots", "checked": "2026-11-09", "evidence": {"omakase": "x"}}
    assert category_reasons(g, [], bad) == {}


def test_decode_follows_the_charset_and_falls_back_to_windows_1252():
    assert menus.decode("18 courses • $225".encode("cp1252")) == "18 courses • $225"
    assert menus.decode("Café".encode("utf-8")) == "Café"
    assert menus.decode('<meta charset="iso-8859-1">Caf\xe9'.encode("latin-1")).endswith("Café")
    assert menus.decode("Café".encode("latin-1"), "text/html; charset=ISO-8859-1") == "Café"


def test_due_reads_only_places_in_the_guide_when_given_a_scope():
    places = {"in": {"website": "https://in.nyc"}, "out": {"website": "https://out.nyc"}}
    assert menus.due(places, {}, "2026-11-09", scope={"in"}) == [("in", "https://in.nyc")]



def test_real_false_matches_from_the_november_crawl_are_not_evidence():
    # Black Forest Brooklyn, Superfine: a 3-course family meal and a one-night holiday menu.
    ev, _ = menus.find_evidence("The German Family Feast for $38/person: A 3 course family-style meal.\n"
                                "2026 THANKSGIVING DINNER PRIX FIXE")
    assert ev == {}
    # Forsythia, Omakase OSUKAA, Le Coucou: still evidence.
    ev, _ = menus.find_evidence("$ 98 (5 courses)\nOmakase 10 Course\nDinner Prix Fixe")
    assert set(ev) == {"tasting-menu", "omakase", "prix-fixe"}



def test_build_rechecks_evidence_an_older_rule_accepted():
    old = ok_menu(**{"prix-fixe": "2026 THANKSGIVING DINNER PRIX FIXE", "tasting-menu": "A 3 course family meal",
                     "omakase": "Edomae Omakase"})
    g = {"name": "X", "primary_type": "restaurant", "found_by": ["details"]}
    assert category_reasons(g, [], old) == {"Omakase & chef's counter": "restaurant's own site"}



def test_a_long_sentence_keeps_the_words_that_matched():
    long = "Set against a striking 1931 mosaic, the room evolves through the day " * 4 + "into an intimate omakase."
    ev, _ = menus.find_evidence(long)
    assert "omakase" in ev["omakase"] and ev["omakase"].startswith("…") and len(ev["omakase"]) <= 221
    # A first-crawl sentence cut at 220 from its start keeps its standing; the one-off check still applies.
    assert menus.current_evidence(ok_menu(omakase=long[:220])) == {"omakase": long[:220]}
