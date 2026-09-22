"""The geography in a Places request body. Restriction hides, bias only ranks — so which one each
call uses is the whole difference between finding another city's venue and not."""

from libs import places


def _body(monkeypatch, fn, *args, **kwargs):
    seen = {}

    def fake(body, limit, timeout):
        seen.update(body)
        return []

    monkeypatch.setattr(places, "_autocomplete", fake)
    fn(*args, **kwargs)
    return seen


def test_the_venue_typeahead_biases_rather_than_restricts(monkeypatch):
    body = _body(monkeypatch, places.search_venues, "opera house", 60.17, 24.94, 50000)

    assert "locationRestriction" not in body
    assert body["locationBias"] == {"circle": {"center": {"latitude": 60.17, "longitude": 24.94},
                                               "radius": 50000.0}}


def test_city_search_is_unbounded(monkeypatch):
    body = _body(monkeypatch, places.search_cities, "tromso")

    assert "locationBias" not in body and "locationRestriction" not in body
    assert body["includedPrimaryTypes"] == ["(cities)"]
