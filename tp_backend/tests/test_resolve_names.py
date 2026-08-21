"""Normalisation, the pre-call junk gate, and confidence. All pure — nothing here touches Places."""

import pytest

from libs.db.enums import Confidence
from libs.places import VenueHit
from tp_ingestions.places import names


def hit(**kw) -> VenueHit:
    return VenueHit(**{"place_id": "p1", "name": "Fjellheisen", "address": "Sollivegen 12",
                       "lat": 69.65, "lon": 18.96, "rating": 4.5, "rating_count": 4466,
                       "primary_type": None, "types": ["point_of_interest"]} | kw)


@pytest.mark.parametrize("a,b", [
    ("Polar Museum", "polar Museum"),
    ("Tromsø Cathedral", "Tromso Cathedral"),
    ("Löyly", "Loyly"),
    ("Raketten Bar & Pølse", "raketten bar polse"),
    ("Vanha  Kauppahalli", "Vanha Kauppahalli"),
])
def test_spellings_of_one_name_share_a_cache_key(a, b):
    assert names.query_norm(a) == names.query_norm(b)


def test_nordic_letters_are_folded_because_nfkd_does_not_decompose_them():
    """ø, æ and å are letters in their own right, so accent-stripping alone leaves them intact."""
    assert names.query_norm("Dragøy") == "dragoy"
    assert names.query_norm("Ærø") == "aero"
    assert names.query_norm("Åre") == "are"


def test_genuinely_different_names_keep_different_keys():
    assert names.query_norm("Senja") != names.query_norm("Senha")
    assert names.query_norm("Cafe Bona") != names.query_norm("Cafe Boner")


def test_cjk_names_survive_normalisation():
    assert names.query_norm("Dragøy海鲜市场") == "dragoy海鲜市场"


@pytest.mark.parametrize("name", ["bakery", "library", "stadium", "cable car", "visitor center",
                                  "Cafe and Restaurant", "Burger", "the bakery", "  BAKERY  "])
def test_a_bare_generic_noun_never_reaches_google(name):
    """Places answers a bare noun with the best-known instance of it, rated 4.7 with 553 reviews.

    Nothing in the response distinguishes that from a real recommendation, so the gate must be here.
    """
    assert names.reject_before_call(name) is not None


@pytest.mark.parametrize("name", ["McDonald's", "Burger King", "Rema 1000", "EUROSPAR",
                                  "Hard Rock Cafe", "Vitusapotek", "7-Eleven"])
def test_chains_never_reach_google(name):
    assert names.reject_before_call(name) is not None


@pytest.mark.parametrize("name", ["Fjellheisen", "Vervet Bakeri", "Bardus Bistro", "Pastafabrikken",
                                  "Raketten Bar & Pølse", "Dragøy海鲜市场", "Polar Museum",
                                  "Mathallen Tromso Food Hall"])
def test_real_venue_names_pass_the_gate(name):
    assert names.reject_before_call(name) is None


def test_a_venue_whose_name_contains_a_generic_word_still_passes():
    """Vervet Bakeri is a bakery. Only a name that is nothing but generics is rejected."""
    assert names.reject_before_call("Vervet Bakeri") is None
    assert names.reject_before_call("Tromsø City Library") is None


def test_an_empty_or_punctuation_only_name_is_rejected():
    assert names.reject_before_call("") is not None
    assert names.reject_before_call("  ???  ") is not None


def test_confidence_comes_from_the_rating_count():
    assert names.judge("Fjellheisen", hit(rating_count=4466))[0] == Confidence.HIGH
    assert names.judge("Fint", hit(rating_count=45))[0] == Confidence.MEDIUM
    assert names.judge("Fint", hit(rating_count=6))[0] == Confidence.LOW


def test_zero_ratings_is_a_rejection_not_a_low_score():
    conf, reason = names.judge("Sentra", hit(rating_count=0))
    assert conf is None and "rating" in reason


def test_a_missing_type_does_not_count_against_a_place():
    """Fjellheisen, Tromsø's top attraction, returns no primaryTypeDisplayName at all."""
    assert names.judge("Fjellheisen", hit(primary_type=None, types=[]))[0] == Confidence.HIGH


@pytest.mark.parametrize("official", ["EUROSPAR Storgata", "Vinmonopolet",
                                      "Comfort Hotel Xpress Tromsø", "Peppes Pizza - Tromsø"])
def test_a_chain_is_rejected_on_the_name_google_returned(official):
    """The query gate only sees what the source wrote: "Storgata" is a street, and it resolved to
    the EUROSPAR on it. Checking the official name too is free and catches the rest."""
    conf, reason = names.judge("Storgata", hit(name=official, rating_count=812))
    assert conf is None and "chain" in reason


def test_a_local_venue_is_not_mistaken_for_a_chain():
    for official in ["Bardus Bistro", "Sabi Sushi Tromsø", "Risø mat og kaffebar", "Ølhallen"]:
        assert names.judge("x", hit(name=official, rating_count=500))[0] is not None


def test_a_cjk_query_resolving_to_a_latin_name_is_unconfirmed():
    conf, reason = names.judge("好餐厅", hit(name="Some Bistro", rating_count=4466))
    assert conf == Confidence.MEDIUM and "unconfirmed" in reason


def test_a_cjk_query_with_a_latin_anchor_is_confirmed_by_that_anchor():
    """Dragøy海鲜市场 -> "Dragøy Coastal Mathus" matched on the Latin fragment, so it is not a guess."""
    conf, _ = names.judge("Dragøy海鲜市场", hit(name="Dragøy Coastal Mathus", rating_count=756))
    assert conf == Confidence.HIGH


def test_distance_is_measured_in_kilometres_at_high_latitude():
    """Longitude degrees shrink with latitude; at Tromsø's 69°N the naive figure is nearly 3x out."""
    assert names.distance_km(69.6492, 18.9553, 69.6492, 18.9553) == pytest.approx(0, abs=0.01)
    far = names.distance_km(69.6492, 18.9553, 69.6492, 20.0)
    assert 38 < far < 46
