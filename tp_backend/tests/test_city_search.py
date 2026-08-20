"""GET /cities/search: the typeahead that supplies a place_id to /initiate-plan."""

import pytest
from fastapi.testclient import TestClient

from libs.places import CitySuggestion, PlacesError
from tp_api.deps import city_search
from tp_api.main import app

SUGGESTIONS = [
    CitySuggestion(place_id="ChIJ_helsinki", description="Helsinki, Finland", main_text="Helsinki"),
    CitySuggestion(place_id="ChIJ_helsingborg", description="Helsingborg, Sweden",
                   main_text="Helsingborg"),
    CitySuggestion(place_id="ChIJ_helsinge", description="Helsinge, Denmark", main_text=None),
]


@pytest.fixture
def search():
    """Stands in for Places autocomplete. Reassign ["fn"] to change what the endpoint sees."""
    return {"fn": lambda q, limit: SUGGESTIONS[:limit]}


@pytest.fixture
def api(search):
    app.dependency_overrides[city_search] = lambda: (lambda q, limit: search["fn"](q, limit))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_returns_suggestions(api):
    r = api.get("/cities/search", params={"q": "helsin"})
    assert r.status_code == 200, r.text
    assert r.json() == [
        {"place_id": "ChIJ_helsinki", "description": "Helsinki, Finland", "main_text": "Helsinki"},
        {"place_id": "ChIJ_helsingborg", "description": "Helsingborg, Sweden",
         "main_text": "Helsingborg"},
        {"place_id": "ChIJ_helsinge", "description": "Helsinge, Denmark", "main_text": None},
    ]


def test_no_matches_is_an_empty_list(api, search):
    search["fn"] = lambda q, limit: []
    r = api.get("/cities/search", params={"q": "zzzzzz"})
    assert r.status_code == 200
    assert r.json() == []


def test_a_one_character_query_is_rejected(api):
    assert api.get("/cities/search", params={"q": "h"}).status_code == 422


def test_a_missing_query_is_rejected(api):
    assert api.get("/cities/search").status_code == 422


def test_places_being_down_is_a_bad_gateway(api, search):
    def boom(q, limit):
        raise PlacesError("places autocomplete returned 500")

    search["fn"] = boom
    r = api.get("/cities/search", params={"q": "helsin"})
    assert r.status_code == 502
    assert "city search failed" in r.json()["detail"]


def test_limit_is_passed_through(api):
    r = api.get("/cities/search", params={"q": "helsin", "limit": 2})
    assert [s["place_id"] for s in r.json()] == ["ChIJ_helsinki", "ChIJ_helsingborg"]


def test_limit_above_ten_is_rejected(api):
    assert api.get("/cities/search", params={"q": "helsin", "limit": 11}).status_code == 422
    assert api.get("/cities/search", params={"q": "helsin", "limit": 0}).status_code == 422
