"""Blocks the shortlist could never hold: a flight, a hotel night, a booked activity."""

from conftest import make_place, plan_body
from sqlalchemy import select

from libs.db import ItineraryItem


def make_trip(client, **kw):
    return client.post("/initiate-plan", json=plan_body(**kw)).json()["trip_id"]


def custom(block_id, start_min=900, duration_min=60, title="Flight SQ 3116", description=None):
    return {"kind": "custom", "block_id": block_id, "title": title, "description": description,
            "start_min": start_min, "duration_min": duration_min}


def put(client, trip, days):
    return client.put(f"/trips/{trip}/itinerary", json={"days": days})


class TestCustomBlocks:
    def test_a_flight_survives_a_reread_with_its_details(self, client):
        trip = make_trip(client)
        put(client, trip, [{"day_index": 0, "items": [
            custom("b1", title="Flight SQ 3116 to Oslo",
                   description="Changi T3, 22:05\nSeat 42K")]}])

        item = client.get(f"/trips/{trip}/itinerary").json()["days"][0]["items"][0]
        assert item["kind"] == "custom"
        assert item["place_id"] is None
        assert item["block_id"] == "b1"
        assert item["name"] == "Flight SQ 3116 to Oslo"
        assert item["description"] == "Changi T3, 22:05\nSeat 42K"

    def test_the_same_stay_on_three_nights(self, client):
        trip = make_trip(client)
        body = put(client, trip, [
            {"day_index": d, "items": [custom(f"hotel-{d}", start_min=21 * 60, duration_min=120,
                                              title="Hotel Bristol")]}
            for d in (0, 1, 2)]).json()

        assert [d["items"][0]["name"] for d in body["days"][:3]] == ["Hotel Bristol"] * 3

    def test_two_blocks_with_one_title_share_a_day(self, client):
        trip = make_trip(client)
        body = put(client, trip, [{"day_index": 1, "items": [
            custom("leg-1", start_min=480, title="Train to Bergen"),
            custom("leg-2", start_min=960, title="Train to Bergen")]}]).json()

        assert [i["block_id"] for i in body["days"][1]["items"]] == ["leg-1", "leg-2"]

    def test_a_place_and_a_custom_block_share_a_day(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Vigeland Park")
        body = put(client, trip, [{"day_index": 1, "items": [
            custom("b1", start_min=480, title="Check in"),
            {"place_id": "p1", "start_min": 600, "duration_min": 90}]}]).json()

        assert [i["kind"] for i in body["days"][1]["items"]] == ["custom", "place"]
        assert [i["name"] for i in body["days"][1]["items"]] == ["Check in", "Vigeland Park"]

    def test_saving_one_day_leaves_another_days_stay_alone(self, client):
        trip = make_trip(client)
        put(client, trip, [{"day_index": 0, "items": [custom("hotel-0", title="Hotel Bristol")]}])

        body = put(client, trip, [{"day_index": 2, "items": [custom("b2", title="Husky sled")]}]).json()
        assert [i["block_id"] for i in body["days"][0]["items"]] == ["hotel-0"]
        assert [i["block_id"] for i in body["days"][2]["items"]] == ["b2"]

    def test_dragging_a_block_off_a_day_the_client_did_not_list(self, client, db):
        """block_id is unique per trip, so the move must delete the old row rather than collide."""
        trip = make_trip(client)
        put(client, trip, [{"day_index": 0, "items": [custom("b1")]}])

        body = put(client, trip, [{"day_index": 1, "items": [custom("b1", start_min=600)]}]).json()
        assert body["days"][0]["items"] == []
        assert [i["start_min"] for i in body["days"][1]["items"]] == [600]
        assert db.scalars(select(ItineraryItem.day_index)).all() == [1]

    def test_a_custom_block_carrying_a_place_id_is_rejected(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        r = put(client, trip, [{"day_index": 0, "items": [custom("b1") | {"place_id": "p1"}]}])
        assert r.status_code == 422

    def test_a_custom_block_without_a_title_is_rejected(self, client):
        trip = make_trip(client)
        r = put(client, trip, [{"day_index": 0, "items": [custom("b1", title=None)]}])
        assert r.status_code == 422

    def test_a_place_block_carrying_a_title_is_rejected(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        r = put(client, trip, [{"day_index": 0, "items": [
            {"place_id": "p1", "title": "Not a place", "start_min": 900, "duration_min": 60}]}])
        assert r.status_code == 422

    def test_the_same_block_id_twice_in_one_payload_is_rejected(self, client):
        trip = make_trip(client)
        r = put(client, trip, [{"day_index": 0, "items": [
            custom("b1", start_min=900), custom("b1", start_min=990)]}])
        assert r.status_code == 422

    def test_a_block_outside_the_flight_window_is_still_rejected(self, client):
        """plan_body lands 14:30: the window is the trip's, not the shortlist's."""
        trip = make_trip(client)
        r = put(client, trip, [{"day_index": 0, "items": [custom("b1", start_min=840)]}])
        assert r.status_code == 422


class TestRouteDayIgnoresThem:
    def test_a_day_of_only_custom_blocks_warns_about_nothing(self, client):
        trip = make_trip(client)
        put(client, trip, [{"day_index": 0, "items": [
            custom("b1", start_min=22 * 60, duration_min=120, title="Flight to Oslo")]}])

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["warnings"] == []
        assert [(b["name"], b["kind"]) for b in body["blocks"]] == [("Flight to Oslo", "custom")]

    def test_a_custom_block_is_echoed_with_its_own_times_and_details(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Vigeland Park")
        put(client, trip, [{"day_index": 1, "items": [
            custom("b1", start_min=480, duration_min=90, title="Check in",
                   description="Kristian IVs gate 7"),
            {"place_id": "p1", "start_min": 600, "duration_min": 60}]}])

        blocks = client.post(f"/trips/{trip}/days/1/route", json={}).json()["blocks"]
        assert blocks[0] == {"kind": "custom", "place_id": None, "block_id": "b1",
                             "name": "Check in", "description": "Kristian IVs gate 7",
                             "start": "08:00", "end": "09:30", "duration_min": 90,
                             "open_from": None, "open_to": None}
        assert blocks[1]["place_id"] == "p1"

    def test_hours_are_only_fetched_for_the_places(self, client, db, hours):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Vigeland Park")
        put(client, trip, [{"day_index": 1, "items": [
            custom("b1", start_min=480, title="Check in"),
            {"place_id": "p1", "start_min": 600, "duration_min": 60}]}])
        asked = []

        def counting(place_ids):
            asked.append(list(place_ids))
            return {}

        hours["fn"] = counting
        client.post(f"/trips/{trip}/days/1/route", json={})
        assert asked == [["p1"]]
