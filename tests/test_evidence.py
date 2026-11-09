"""A themed search tags a restaurant only with evidence it fits (owner ruling, 2026-11-09).

The first live run showed why. "Tasting menu" in Manhattan returned Daniel,
Atomix and The Musket Room; in the Bronx, where there are few tasting menus,
Google fell back to good restaurants nearby (Cap't Loui seafood, Nana's
Kitchen), and every one of them was tagged "Tasting menu". The cases below are
those real places, reduced to the fields the rule reads.
"""
import pytest

from nyceats.build import categories_for, theme_evidence


def place(name, primary_type="restaurant", price=None, summary=None, found_by=("themed:tasting-menu",)):
    return {"name": name, "primary_type": primary_type, "price_level": price, "summary": summary,
            "found_by": list(found_by)}


@pytest.mark.parametrize("p,expected", [
    (place("Daniel", "french_restaurant", 4), "price $$$$"),
    (place("Luthun", "fine_dining_restaurant", None), "Google type fine_dining_restaurant"),
    (place("Shinzo Omakase", "sushi_restaurant", 3), "name or summary mentions 'omakase'"),
    (place("Kono", "yakitori_restaurant", None, "Intimate counter serving a chicken tasting menu"),
     "name or summary mentions 'tasting'"),
    # The Bronx fall-backs: no type, no keyword, no price signal.
    (place("Cap't Loui Throggs Neck", "seafood_restaurant", None), None),
    (place("Nana's Kitchen", "eastern_european_restaurant", 1), None),
    (place("Lava Rock Kitchen", "restaurant", 2), None),
])
def test_tasting_menu_evidence(p, expected):
    assert theme_evidence("tasting-menu", p) == expected


def test_a_protein_theme_needs_the_protein_named():
    assert theme_evidence("goat", place("Birria-Landia", summary="Goat birria tacos", found_by=["themed:goat"])) \
        == "name or summary mentions 'goat'"
    # An expensive steakhouse returned for "goat" is still not evidence of goat.
    assert theme_evidence("goat", place("Steak Palace", "steak_house", 4, found_by=["themed:goat"])) is None


def test_price_counts_for_tasting_but_not_for_fine_dining_below_four():
    assert theme_evidence("fine-dining", place("X", price=3, found_by=["themed:fine-dining"])) is None
    assert theme_evidence("fine-dining", place("X", price=4, found_by=["themed:fine-dining"])) == "price $$$$"


def test_categories_keep_only_evidenced_themes_and_count_the_rest():
    dropped = []
    cats = categories_for(place("Lena Trattoria", "italian_restaurant", 2,
                                found_by=["themed:tasting-menu", "nearby"]), dropped)
    assert cats == [] and dropped == ["tasting-menu"]
    cats = categories_for(place("Atomix", "korean_restaurant", 4,
                                found_by=["themed:tasting-menu", "themed:wagyu"]), dropped)
    assert cats == ["Tasting menu"]  # wagyu needs the word; price is not evidence of a protein


def test_googles_fine_dining_type_is_a_category_on_its_own():
    assert categories_for(place("Luthun", "fine_dining_restaurant", found_by=["nearby"]), []) == ["Fine dining"]
