"""DELETE /trips/{id}: soft, so the ordering work a trip carries survives a mis-click."""

from conftest import make_mention, make_place, plan_body
from sqlalchemy import func, select

from libs.db import ItineraryItem, Trip


def make_trip(client, **kw):
    return client.post("/initiate-plan", json=plan_body(**kw)).json()["trip_id"]


def test_deleting_flags_the_trip(client, db):
    trip_id = make_trip(client)

    assert client.delete(f"/trips/{trip_id}").status_code == 204

    db.expire_all()
    assert db.get(Trip, trip_id).deleted is True


def test_a_deleted_trip_leaves_the_list(client):
    trip_id = make_trip(client)
    assert [t["trip_id"] for t in client.get("/trips").json()] == [trip_id]

    client.delete(f"/trips/{trip_id}")

    assert client.get("/trips").json() == []


def test_the_trip_still_loads_and_says_it_is_deleted(client):
    trip_id = make_trip(client)
    assert client.get(f"/trips/{trip_id}").json()["deleted"] is False

    client.delete(f"/trips/{trip_id}")

    body = client.get(f"/trips/{trip_id}").json()
    assert body["deleted"] is True
    assert body["trip_id"] == trip_id


def test_deleting_twice_is_still_a_204(client):
    trip_id = make_trip(client)
    assert client.delete(f"/trips/{trip_id}").status_code == 204
    assert client.delete(f"/trips/{trip_id}").status_code == 204


def test_an_unknown_trip_is_a_404(client):
    assert client.delete("/trips/nope").status_code == 404


def test_the_ordering_work_survives(client, db):
    """The whole point of soft-deleting: days the user built are not thrown away."""
    trip_id = make_trip(client)
    make_place(db, place_id="p1")
    make_mention(db, "p1")
    client.put(f"/trips/{trip_id}/itinerary",
               json={"days": [{"day_index": 0,
                               "items": [{"place_id": "p1", "start_min": 900,
                                          "duration_min": 60}]}]})

    client.delete(f"/trips/{trip_id}")

    assert db.scalar(select(func.count()).select_from(ItineraryItem)
                     .where(ItineraryItem.trip_id == trip_id)) == 1
