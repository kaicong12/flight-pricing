"""Adding a place by hand: the venue typeahead, and the insert that makes it shortlistable."""

import pytest
from conftest import HELSINKI, make_mention, make_place, plan_body
from sqlalchemy import select

from libs.db import Place, TripDismissal
from libs.places import PlacesError, VenueHit, VenueSuggestion
from tp_api.deps import venue_lookup, venue_search
from tp_api.main import app

# Helsinki in conftest sits at 60.17/24.94; the default radius is 50km.
OODI = VenueHit(place_id="ChIJ_oodi", name="Oodi Library", address="Töölönlahdenkatu 4",
                lat=60.1755, lon=24.9375, rating=4.6, rating_count=9000,
                primary_type="Library", types=["library"])
FAR_AWAY = VenueHit(place_id="ChIJ_sydney", name="Sydney Opera House", address="Bennelong Point",
                    lat=-33.8568, lon=151.2153, rating=4.7, rating_count=100000,
                    primary_type="Opera house", types=["tourist_attraction"])


@pytest.fixture
def venues():
    """Stands in for Places autocomplete and Place Details. Reassign ["fn"] to change the answer."""
    return {
        "search": lambda q, lat, lon, radius: [
            VenueSuggestion(place_id="ChIJ_oodi", name="Oodi Library", context="Helsinki, Finland"),
        ],
        "lookup": lambda place_id: OODI if place_id == OODI.place_id else None,
    }


@pytest.fixture(autouse=True)
def _wire(venues, client):
    app.dependency_overrides[venue_search] = lambda: (
        lambda q, lat, lon, radius: venues["search"](q, lat, lon, radius))
    app.dependency_overrides[venue_lookup] = lambda: (lambda pid: venues["lookup"](pid))
    yield


def make_trip(client, **kw):
    return client.post("/initiate-plan", json=plan_body(**kw)).json()["trip_id"]


def add(client, trip, place_id, category="see"):
    return client.post(f"/trips/{trip}/places",
                       json={"place_id": place_id, "category": category})


class TestSearch:
    def test_returns_suggestions(self, client):
        trip = make_trip(client)
        r = client.get(f"/trips/{trip}/places/search", params={"q": "oodi"})
        assert r.status_code == 200, r.text
        assert r.json() == [{"place_id": "ChIJ_oodi", "name": "Oodi Library",
                             "context": "Helsinki, Finland"}]

    def test_searches_near_the_trips_city(self, client, venues):
        """The city box is what stops a namesake in another country coming back."""
        seen = {}

        def spy(q, lat, lon, radius):
            seen.update(q=q, lat=lat, lon=lon, radius=radius)
            return []

        venues["search"] = spy
        client.get(f"/trips/{make_trip(client)}/places/search", params={"q": "oodi"})
        assert seen == {"q": "oodi", "lat": 60.17, "lon": 24.94, "radius": 50000}

    def test_one_letter_is_rejected(self, client):
        r = client.get(f"/trips/{make_trip(client)}/places/search", params={"q": "o"})
        assert r.status_code == 422

    def test_unknown_trip_is_a_404(self, client):
        assert client.get("/trips/nope/places/search", params={"q": "oodi"}).status_code == 404

    def test_a_places_outage_is_a_502(self, client, venues):
        venues["search"] = lambda *a: (_ for _ in ()).throw(PlacesError("boom"))
        r = client.get(f"/trips/{make_trip(client)}/places/search", params={"q": "oodi"})
        assert r.status_code == 502


class TestAdd:
    def test_adding_returns_the_place_and_stores_it(self, client, db):
        trip = make_trip(client)
        r = add(client, trip, "ChIJ_oodi")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["place_id"] == "ChIJ_oodi"
        assert body["name"] == "Oodi Library"
        assert body["lat"] == pytest.approx(60.1755)
        # No mentions, because nothing named it — it is the user's own choice.
        assert body["mention_count"] == 0
        assert body["sources"] == []
        assert body["in_itinerary"] is False

        stored = db.scalar(select(Place).where(Place.place_id == "ChIJ_oodi"))
        assert stored is not None
        assert stored.city_id == HELSINKI

    def test_it_then_appears_in_the_shortlist(self, client, db):
        """The whole point: `places` scoped to the city is what the shortlist reads."""
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Mentioned")
        make_mention(db, "p1")

        add(client, trip, "ChIJ_oodi")

        places = client.get(f"/trips/{trip}/shortlist").json()["places"]
        # Last, since ranking is by mention count and a hand-added place has none.
        assert [p["name"] for p in places] == ["Mentioned", "Oodi Library"]

    def test_it_can_be_dragged_onto_a_day(self, client):
        """A manual place must clear replace_days' "is it a place in this city" gate."""
        trip = make_trip(client)
        add(client, trip, "ChIJ_oodi")

        # Day 0 is only usable from the arrival time, so this sits after the flight lands.
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [
                {"place_id": "ChIJ_oodi", "start_min": 15 * 60, "duration_min": 60}]}]})
        assert r.status_code == 200, r.text
        assert client.get(f"/trips/{trip}/shortlist").json()["places"][0]["in_itinerary"] is True

    def test_a_place_far_from_the_city_is_accepted(self, client, db, venues):
        """No distance is modelled anywhere, so nothing here can call a place too far away."""
        venues["lookup"] = lambda pid: FAR_AWAY
        trip = make_trip(client)

        r = add(client, trip, "ChIJ_sydney")

        assert r.status_code == 200, r.text
        assert db.scalar(select(Place).where(Place.place_id == "ChIJ_sydney")) is not None
        names = [p["name"] for p in client.get(f"/trips/{trip}/shortlist").json()["places"]]
        assert "Sydney Opera House" in names

    def test_another_trips_hand_added_place_is_not_on_this_shortlist(self, client, db, venues):
        """Trip-scoped: what one trip added by hand is that trip's, not the whole city's."""
        venues["lookup"] = lambda pid: FAR_AWAY
        mine, theirs = make_trip(client), make_trip(client)
        add(client, theirs, "ChIJ_sydney")

        names = [p["name"] for p in client.get(f"/trips/{mine}/shortlist").json()["places"]]
        assert "Sydney Opera House" not in names

    def test_an_unknown_place_id_is_refused(self, client, venues):
        """Google answers a malformed id with a 400 and an unknown one with a 404; venue_details
        maps both to None, so neither reaches the user as a 502."""
        venues["lookup"] = lambda pid: None
        r = add(client, make_trip(client), "nope")
        assert r.status_code == 422

    def test_adding_one_already_in_the_city_spends_nothing(self, client, db, venues):
        """A place the ingestion already found needs no Places call to re-add."""
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Already Here")
        venues["lookup"] = lambda pid: pytest.fail("should not call Places")

        r = add(client, trip, "p1")
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Already Here"

    def test_adding_a_dismissed_place_brings_it_back(self, client, db):
        """Otherwise adding it looks like it silently did nothing — the dismissal still hides it."""
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Struck Off")
        client.post(f"/trips/{trip}/dismissals", json={"place_id": "p1"})
        assert client.get(f"/trips/{trip}/shortlist").json()["places"] == []

        add(client, trip, "p1")

        names = [p["name"] for p in client.get(f"/trips/{trip}/shortlist").json()["places"]]
        assert names == ["Struck Off"]
        assert db.scalar(select(TripDismissal).where(TripDismissal.trip_id == trip)) is None

    def test_adding_twice_is_harmless(self, client):
        trip = make_trip(client)
        first = add(client, trip, "ChIJ_oodi")
        second = add(client, trip, "ChIJ_oodi")
        assert first.status_code == 200
        assert second.status_code == 200
        assert client.get(f"/trips/{trip}/shortlist").json()["total"] == 1

    def test_a_places_outage_is_a_502(self, client, venues):
        venues["lookup"] = lambda pid: (_ for _ in ()).throw(PlacesError("boom"))
        r = add(client, make_trip(client), "ChIJ_oodi")
        assert r.status_code == 502

    def test_unknown_trip_is_a_404(self, client):
        assert add(client, "nope", "ChIJ_oodi").status_code == 404

    def test_the_category_is_compulsory(self, client):
        """Without one a manual place has no category at all — mentions are where the rest come from,
        and it has none — so it would be invisible under every filter chip."""
        trip = make_trip(client)
        assert client.post(f"/trips/{trip}/places",
                           json={"place_id": "ChIJ_oodi"}).status_code == 422

    def test_a_category_outside_the_vocabulary_is_refused(self, client):
        assert add(client, make_trip(client), "ChIJ_oodi", "vibes").status_code == 422

    def test_the_chosen_category_survives_the_filter(self, client, db):
        """The point of storing it: the place must still be there when a chip is active."""
        trip = make_trip(client)
        add(client, trip, "ChIJ_oodi", "eat")

        assert [p["name"] for p in
                client.get(f"/trips/{trip}/shortlist", params={"category": "eat"})
                .json()["places"]] == ["Oodi Library"]
        assert client.get(f"/trips/{trip}/shortlist",
                          params={"category": "see"}).json()["places"] == []

    def test_a_persons_category_beats_the_videos(self, client, db):
        """mention_facts takes a majority vote of what the sources said; a human overrules it."""
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Called A Bar By Videos")
        make_mention(db, "p1", category="drink")
        venues_hit = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert venues_hit["category"] == "drink"

        assert add(client, trip, "p1", "eat").json()["category"] == "eat"
        assert client.get(f"/trips/{trip}/shortlist").json()["places"][0]["category"] == "eat"
