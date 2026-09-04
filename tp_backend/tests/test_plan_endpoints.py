"""The planning screen's endpoints: shortlist ranking, the user's ordering, and a routed day."""

from datetime import timedelta

from conftest import make_mention, make_note, make_place, make_video, plan_body
from sqlalchemy import select

from libs.db import ItineraryItem
from libs.db.enums import Sentiment, Source
from libs.routing import HoursHit, Leg, RouteResult
from tp_api.plan_schemas import REGULAR_HOURS_ONLY_NOTE
from tp_api.schemas import TRANSIT_HORIZON_NOTE, today_utc

OPEN_ALL_WEEK = [{"open": {"day": d, "hour": 9, "minute": 0},
                  "close": {"day": d, "hour": 18, "minute": 0}} for d in range(7)]


def make_trip(client, **kw):
    return client.post("/initiate-plan", json=plan_body(**kw)).json()["trip_id"]


def seed(db, *specs):
    """specs are (place_id, name, mention_count) — the shortlist's ranking signal."""
    for place_id, name, mentions in specs:
        make_place(db, place_id=place_id, name=name)
        for i in range(mentions):
            make_mention(db, place_id, source_ref=f"{place_id}-{i}")


class TestShortlist:
    def test_unknown_trip_is_a_404(self, client):
        assert client.get("/trips/nope/shortlist").status_code == 404

    def test_a_city_with_no_places_is_empty_not_an_error(self, client):
        body = client.get(f"/trips/{make_trip(client)}/shortlist").json()
        assert body == {"total": 0, "shown": 0, "places": []}

    def test_ranked_by_how_many_sources_mentioned_it(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "One mention", 1), ("p2", "Three mentions", 3), ("p3", "Two mentions", 2))

        places = client.get(f"/trips/{trip}/shortlist").json()["places"]

        assert [p["name"] for p in places] == ["Three mentions", "Two mentions", "One mention"]
        assert [p["mention_count"] for p in places] == [3, 2, 1]

    def test_a_place_with_no_mentions_still_appears_last(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Mentioned")
        make_mention(db, "p1")
        make_place(db, place_id="p2", name="Unmentioned")

        places = client.get(f"/trips/{trip}/shortlist").json()["places"]
        assert [p["name"] for p in places] == ["Mentioned", "Unmentioned"]
        assert places[1]["mention_count"] == 0

    def test_ties_break_on_rating_count(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Quiet", rating_count=10)
        make_mention(db, "p1")
        make_place(db, place_id="p2", name="Famous", rating_count=9000)
        make_mention(db, "p2")

        places = client.get(f"/trips/{trip}/shortlist").json()["places"]
        assert [p["name"] for p in places] == ["Famous", "Quiet"]

    def test_every_mention_becomes_one_linked_source(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_video(db, video_id="vid1", title="Tromsø in 3 Days")
        make_note(db, note_id="note1", title="特罗姆瑟美食", xsec_token="tok")
        make_mention(db, "p1", source=Source.YOUTUBE, source_ref="vid1")
        make_mention(db, "p1", source=Source.REDNOTE, source_ref="note1")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]

        assert p["mention_count"] == 2
        assert p["sources"] == [
            {"source": "rednote", "title": "特罗姆瑟美食",
             "url": "https://www.xiaohongshu.com/explore/note1?xsec_token=tok"},
            {"source": "youtube", "title": "Tromsø in 3 Days",
             "url": "https://www.youtube.com/watch?v=vid1"},
        ]

    def test_a_note_without_a_token_still_gets_a_link(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_note(db, note_id="note1", xsec_token=None)
        make_mention(db, "p1", source=Source.REDNOTE, source_ref="note1")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["sources"][0]["url"] == "https://www.xiaohongshu.com/explore/note1"

    def test_a_titleless_note_falls_back_to_its_description(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_note(db, note_id="note1", title=None, description="八家必吃的店，人均一百出头")
        make_mention(db, "p1", source=Source.REDNOTE, source_ref="note1")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["sources"][0]["title"] == "八家必吃的店，人均一百出头"

    def test_a_mention_whose_source_row_is_gone_is_still_clickable(self, client, db):
        """The mention outlives the cache row it came from, so a missing join must not lose the link."""
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_mention(db, "p1", source=Source.YOUTUBE, source_ref="vid1")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["sources"] == [{"source": "youtube", "title": "YouTube video",
                                 "url": "https://www.youtube.com/watch?v=vid1"}]

    def test_an_escaped_youtube_title_is_readable(self, client, db):
        """YouTube hands back "&amp;", which would otherwise render literally in the link."""
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_video(db, video_id="vid1", title="Tromsø In &amp; Around")
        make_mention(db, "p1", source=Source.YOUTUBE, source_ref="vid1")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["sources"][0]["title"] == "Tromsø In & Around"

    def test_ratings_are_not_in_the_payload(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", rating=4.5, rating_count=9000)

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert "rating" not in p and "rating_count" not in p

    def test_category_is_the_modal_mention(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_mention(db, "p1", category="eat", source_ref="a")
        make_mention(db, "p1", category="eat", source_ref="b")
        make_mention(db, "p1", category="see", source_ref="c")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["category"] == "eat"

    def test_the_blurb_is_the_fullest_recommendation(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_mention(db, "p1", why_go="Good", source_ref="a")
        make_mention(db, "p1", why_go="The one everyone sends you to for lunch", source_ref="b")

        p = client.get(f"/trips/{trip}/shortlist").json()["places"][0]
        assert p["why_go"] == "The one everyone sends you to for lunch"

    def test_a_pans_why_go_is_never_the_blurb(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1")
        make_mention(db, "p1", why_go="Tourist trap, skip it",
                     sentiment=Sentiment.NOT_RECOMMENDED)

        assert client.get(f"/trips/{trip}/shortlist").json()["places"][0]["why_go"] is None

    def test_total_is_the_whole_city_while_shown_is_the_page(self, client, db):
        trip = make_trip(client)
        seed(db, *[(f"p{i}", f"Place {i}", i) for i in range(1, 6)])

        body = client.get(f"/trips/{trip}/shortlist?limit=2").json()
        assert body["total"] == 5
        assert body["shown"] == 2

    def test_paging_walks_the_ranking(self, client, db):
        trip = make_trip(client)
        seed(db, *[(f"p{i}", f"Place {i}", i) for i in range(1, 6)])

        first = client.get(f"/trips/{trip}/shortlist?limit=2").json()["places"]
        second = client.get(f"/trips/{trip}/shortlist?limit=2&offset=2").json()["places"]
        assert [p["name"] for p in first] == ["Place 5", "Place 4"]
        assert [p["name"] for p in second] == ["Place 3", "Place 2"]

    def test_another_citys_places_are_not_listed(self, client, db):
        trip = make_trip(client)
        from conftest import make_city
        make_city(db, city_id="other", name="Bergen")
        make_place(db, city_id="other", place_id="p9", name="Elsewhere")

        assert client.get(f"/trips/{trip}/shortlist").json()["places"] == []

    def test_filtering_by_category(self, client, db):
        trip = make_trip(client)
        make_place(db, place_id="p1", name="Restaurant")
        make_mention(db, "p1", category="eat")
        make_place(db, place_id="p2", name="Museum")
        make_mention(db, "p2", category="see")

        places = client.get(f"/trips/{trip}/shortlist?category=eat").json()["places"]
        assert [p["name"] for p in places] == ["Restaurant"]

    def test_a_place_on_a_day_is_flagged_with_that_day(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "Added", 1), ("p2", "Not added", 1))
        client.put(f"/trips/{trip}/itinerary",
                   json={"days": [{"day_index": 2,
                                   "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]})

        by_name = {p["name"]: p for p in client.get(f"/trips/{trip}/shortlist").json()["places"]}
        assert by_name["Added"]["in_itinerary"] is True
        assert by_name["Added"]["day_index"] == 2
        assert by_name["Not added"]["in_itinerary"] is False
        assert by_name["Not added"]["day_index"] is None


class TestDismissals:
    def test_a_dismissed_place_leaves_the_shortlist(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "Raketten", 3), ("p2", "Raketten duplicate", 1))

        assert client.post(f"/trips/{trip}/dismissals",
                           json={"place_id": "p2"}).status_code == 204

        body = client.get(f"/trips/{trip}/shortlist").json()
        assert [p["name"] for p in body["places"]] == ["Raketten"]
        assert body["total"] == 1

    def test_dismissing_twice_is_not_an_error(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        for _ in range(2):
            assert client.post(f"/trips/{trip}/dismissals",
                               json={"place_id": "p1"}).status_code == 204

    def test_undismissing_brings_it_back(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        client.post(f"/trips/{trip}/dismissals", json={"place_id": "p1"})

        assert client.delete(f"/trips/{trip}/dismissals/p1").status_code == 204
        assert len(client.get(f"/trips/{trip}/shortlist").json()["places"]) == 1

    def test_one_trips_dismissal_does_not_touch_another(self, client, db):
        a, b = make_trip(client), make_trip(client)
        seed(db, ("p1", "A", 1))
        client.post(f"/trips/{a}/dismissals", json={"place_id": "p1"})

        assert client.get(f"/trips/{a}/shortlist").json()["places"] == []
        assert len(client.get(f"/trips/{b}/shortlist").json()["places"]) == 1

    def test_a_place_from_another_city_is_rejected(self, client, db):
        trip = make_trip(client)
        assert client.post(f"/trips/{trip}/dismissals",
                           json={"place_id": "nope"}).status_code == 422


class TestItineraryRead:
    def test_every_day_of_the_trip_appears_even_when_empty(self, client):
        # plan_body is a 3-night trip, so four days inclusive.
        days = client.get(f"/trips/{make_trip(client)}/itinerary").json()["days"]
        assert [d["day_index"] for d in days] == [0, 1, 2, 3]
        assert all(d["items"] == [] for d in days)

    def test_dates_run_from_arrival(self, client):
        trip = client.post("/initiate-plan", json=plan_body()).json()
        days = client.get(f"/trips/{trip['trip_id']}/itinerary").json()["days"]
        assert days[0]["date"] == trip["arrive_date"]
        assert days[-1]["date"] == trip["depart_date"]

    def test_unknown_trip_is_a_404(self, client):
        assert client.get("/trips/nope/itinerary").status_code == 404


class TestItineraryWrite:
    def test_a_day_is_stored_in_the_order_it_was_sent(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "First", 1), ("p2", "Second", 1), ("p3", "Third", 1))

        body = client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
            {"place_id": "p3", "start_min": 540, "duration_min": 60},
            {"place_id": "p1", "start_min": 630, "duration_min": 90},
            {"place_id": "p2", "start_min": 720, "duration_min": 30},
        ]}]}).json()

        assert [i["name"] for i in body["days"][0]["items"]] == ["Third", "First", "Second"]
        assert [i["start_min"] for i in body["days"][0]["items"]] == [540, 630, 720]
        assert [i["duration_min"] for i in body["days"][0]["items"]] == [60, 90, 30]

    def test_swapping_two_blocks_swaps_their_times(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))

        put_day(client, trip, ["p1", "p2"])
        body = put_day(client, trip, ["p2", "p1"]).json()

        assert [i["place_id"] for i in body["days"][0]["items"]] == ["p2", "p1"]
        assert [i["start_min"] for i in body["days"][0]["items"]] == [540, 630]

    def test_the_order_survives_a_reread(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
            {"place_id": "p2", "start_min": 540, "duration_min": 60}, {"place_id": "p1", "start_min": 630, "duration_min": 60}]}]})

        days = client.get(f"/trips/{trip}/itinerary").json()["days"]
        assert [i["place_id"] for i in days[0]["items"]] == ["p2", "p1"]

    def test_an_empty_day_clears_it(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]})

        body = client.put(f"/trips/{trip}/itinerary",
                          json={"days": [{"day_index": 0, "items": []}]}).json()
        assert body["days"][0]["items"] == []

    def test_days_the_client_did_not_list_are_left_alone(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]},
            {"day_index": 1, "items": [{"place_id": "p2", "start_min": 540, "duration_min": 60}]}]})

        body = client.put(f"/trips/{trip}/itinerary",
                          json={"days": [{"day_index": 0, "items": []}]}).json()
        assert body["days"][0]["items"] == []
        assert [i["place_id"] for i in body["days"][1]["items"]] == ["p2"]

    def test_dragging_a_place_to_another_day_moves_it(self, client, db):
        """The client sends both days, and the place must not collide with its own old row."""
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]})

        body = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": []},
            {"day_index": 1, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]}).json()

        assert body["days"][0]["items"] == []
        assert [i["place_id"] for i in body["days"][1]["items"]] == ["p1"]
        assert db.scalar(select(ItineraryItem.day_index)) == 1

    def test_stealing_a_place_from_a_day_the_client_did_not_list(self, client, db):
        """Only day 1 is sent, but the place currently sits on day 0. It moves, not 409s."""
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]})

        body = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 1, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]}).json()

        assert body["days"][0]["items"] == []
        assert [i["place_id"] for i in body["days"][1]["items"]] == ["p1"]
        assert db.scalars(select(ItineraryItem.place_id)).all() == ["p1"]

    def test_the_same_place_twice_in_one_payload_is_rejected(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
            {"place_id": "p1", "start_min": 540, "duration_min": 60}, {"place_id": "p1", "start_min": 630, "duration_min": 60}]}]})
        assert r.status_code == 422

    def test_the_same_place_on_two_days_in_one_payload_is_rejected(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]},
            {"day_index": 1, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 60}]}]})
        assert r.status_code == 422

    def test_one_day_listed_twice_is_rejected(self, client, db):
        trip = make_trip(client)
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": []}, {"day_index": 0, "items": []}]})
        assert r.status_code == 422

    def test_a_day_beyond_the_trip_is_rejected(self, client):
        trip = make_trip(client)
        r = client.put(f"/trips/{trip}/itinerary",
                       json={"days": [{"day_index": 9, "items": []}]})
        assert r.status_code == 422

    def test_a_place_from_another_city_is_rejected(self, client, db):
        trip = make_trip(client)
        from conftest import make_city
        make_city(db, city_id="other", name="Bergen")
        make_place(db, city_id="other", place_id="p9", name="Elsewhere")

        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p9", "start_min": 540, "duration_min": 60}]}]})
        assert r.status_code == 422

    def test_a_duration_off_the_grid_is_rejected(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [
            {"day_index": 0, "items": [{"place_id": "p1", "start_min": 540, "duration_min": 0}]}]})
        assert r.status_code == 422

    def test_more_stops_than_a_day_takes_is_rejected(self, client, db):
        trip = make_trip(client)
        r = client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": 0, "items": [
            {"place_id": f"p{i}", "start_min": 540, "duration_min": 60} for i in range(26)]}]})
        assert r.status_code == 422

    def test_unknown_trip_is_a_404(self, client):
        r = client.put("/trips/nope/itinerary",
                       json={"days": [{"day_index": 0, "items": []}]})
        assert r.status_code == 404


def put_day(client, trip, ids, day=0, start=540, step=90):
    """Blocks pinned from 09:00, 90 minutes apart, so a 60-minute stop leaves a 30-minute gap."""
    return client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": day, "items": [
        {"place_id": pid, "start_min": start + step * i, "duration_min": 60}
        for i, pid in enumerate(ids)]}]})


def open_hours(place_ids):
    return {p: HoursHit(place_id=p, periods=OPEN_ALL_WEEK, weekday_descriptions=[],
                        utc_offset_minutes=120, has_hours=True) for p in place_ids}


class TestRouteDay:
    def test_unknown_trip_is_a_404(self, client):
        assert client.post("/trips/nope/days/0/route", json={}).status_code == 404

    def test_a_day_beyond_the_trip_is_a_422(self, client):
        trip = make_trip(client)
        assert client.post(f"/trips/{trip}/days/9/route", json={}).status_code == 422

    def test_an_empty_day_is_not_an_error(self, client):
        trip = make_trip(client)
        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["blocks"] == []
        assert body["legs"] == []

    def test_block_times_are_the_pinned_ones_not_a_derived_schedule(self, client, db, hours,
                                                                    routes):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"], start=600, step=90)
        hours["fn"] = open_hours

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()

        # 10:00 and 11:30 as stored. The old endpoint would have derived 11:10 from the 10 min walk.
        assert [(b["start"], b["end"]) for b in body["blocks"]] == [("10:00", "11:00"),
                                                                    ("11:30", "12:30")]
        assert body["start_time"] == "10:00:00"
        assert body["legs"][0]["seconds"] == 600
        assert body["legs"][0]["meters"] == 800
        assert body["legs"][0]["from_place_id"] == "p1"
        assert body["legs"][0]["to_place_id"] == "p2"

    def test_a_one_stop_day_spends_no_routes_call(self, client, db, routes):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])
        called = []
        routes["fn"] = lambda ids, mode, iso: called.append(ids) or RouteResult([], None, 0, 0)

        body = client.post(f"/trips/{trip}/days/0/route", json={"start_time": "09:00"}).json()

        assert called == []
        assert len(body["blocks"]) == 1
        assert body["legs"] == []
        # Not "unrouted": there was nothing to route, which is different from having no answer.
        assert body["routed"] is True

    def test_the_polyline_reaches_the_client(self, client, db, hours):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"])

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["polyline"] == "_p~iF~ps|U"
        assert body["total_distance_m"] == 800

    def test_open_hours_reach_the_blocks(self, client, db, hours):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])
        hours["fn"] = open_hours

        block = client.post(f"/trips/{trip}/days/0/route",
                            json={"start_time": "10:00"}).json()["blocks"][0]
        assert (block["open_from"], block["open_to"]) == ("09:00", "18:00")

    def test_a_block_that_runs_past_closing_warns(self, client, db, hours):
        trip = make_trip(client)
        seed(db, ("p1", "Museum", 1))
        put_day(client, trip, ["p1"], start=17 * 60 + 30)
        hours["fn"] = open_hours

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        warning = next(w for w in body["warnings"] if w["code"] == "closes_before_done")
        assert warning["place_id"] == "p1"
        assert warning["detail"]["closes"] == "18:00"

    def test_hours_we_never_fetched_warn_rather_than_fail(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert [w["code"] for w in body["warnings"]] == ["no_hours"]

    def test_hours_are_cached_so_a_reroute_does_not_refetch(self, client, db, hours):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])
        calls = []

        def counting(place_ids):
            calls.append(list(place_ids))
            return open_hours(place_ids)

        hours["fn"] = counting
        client.post(f"/trips/{trip}/days/0/route", json={})
        client.post(f"/trips/{trip}/days/0/route", json={})

        assert calls == [["p1"]]

    def test_daylight_is_computed_locally(self, client, db):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["daylight"]["sunrise"] < body["daylight"]["sunset"]

    def test_the_days_start_time_is_its_first_block(self, client, db):
        """No day-level start any more: the flight time and the 09:00 default both stop mattering."""
        trip = make_trip(client)  # plan_body arrives at 14:30
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"], start=7 * 60 + 30)

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["start_time"] == "07:30:00"
        assert body["blocks"][0]["start"] == "07:30"

    def test_an_empty_day_has_no_start_time(self, client, db):
        trip = make_trip(client)
        body = client.post(f"/trips/{trip}/days/1/route", json={}).json()
        assert body["start_time"] is None

    def test_transit_steps_reach_the_client(self, client, db, routes):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"])
        routes["fn"] = lambda ids, mode, iso: RouteResult(
            legs=[Leg(seconds=1122, meters=6000, transit_steps=["M1: Kamppi → Ruoholahti"],
                      polyline="abc")],
            polyline=None, total_seconds=1122, total_meters=6000)

        body = client.post(f"/trips/{trip}/days/0/route", json={"mode": "transit"}).json()
        assert body["legs"][0]["transit_steps"] == ["M1: Kamppi → Ruoholahti"]
        assert body["legs"][0]["polyline"] == "abc"

    def test_no_route_at_all_degrades_instead_of_failing(self, client, db, routes):
        """Beyond the transit horizon Routes answers 200 with nothing. That is not a 502."""
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"])
        routes["fn"] = lambda ids, mode, iso: RouteResult([], None, 0, 0)

        r = client.post(f"/trips/{trip}/days/0/route", json={"mode": "transit"})

        assert r.status_code == 200
        body = r.json()
        assert body["routed"] is False
        assert "no_route" in [w["code"] for w in body["warnings"]]
        # The blocks keep their pinned times; only the travel claim is withheld.
        assert [b["start"] for b in body["blocks"]] == ["09:00", "10:30"]

    def test_an_unrouted_day_does_not_also_claim_each_pair_is_unreachable(self, client, db, routes):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"])
        routes["fn"] = lambda ids, mode, iso: RouteResult([], None, 0, 0)

        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert [w["code"] for w in body["warnings"]].count("no_route") == 1

    def test_a_routes_failure_is_a_502(self, client, db, routes):
        from libs.routing import RoutesError
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1))
        put_day(client, trip, ["p1", "p2"])

        def boom(ids, mode, iso):
            raise RoutesError("computeRoutes returned 403")

        routes["fn"] = boom
        assert client.post(f"/trips/{trip}/days/0/route", json={}).status_code == 502

    def test_an_unreachable_places_call_leaves_hours_unknown_rather_than_failing(
            self, client, db, hours):
        from libs.places import PlacesError
        trip = make_trip(client)
        seed(db, ("p1", "A", 1))
        put_day(client, trip, ["p1"])

        def boom(place_ids):
            raise PlacesError("unreachable")

        hours["fn"] = boom
        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert [w["code"] for w in body["warnings"]] == ["no_hours"]

    def test_an_unknown_mode_is_rejected(self, client):
        trip = make_trip(client)
        r = client.post(f"/trips/{trip}/days/0/route", json={"mode": "helicopter"})
        assert r.status_code == 422

    def test_the_route_follows_the_stored_order_not_the_request(self, client, db, routes):
        trip = make_trip(client)
        seed(db, ("p1", "A", 1), ("p2", "B", 1), ("p3", "C", 1))
        put_day(client, trip, ["p3", "p1", "p2"])
        asked = []
        routes["fn"] = lambda ids, mode, iso: asked.append(list(ids)) or RouteResult(
            [Leg(0, 0, [])] * 2, None, 0, 0)

        client.post(f"/trips/{trip}/days/0/route", json={})
        assert asked == [["p3", "p1", "p2"]]


class TestProvisional:
    def test_a_near_trip_is_not_provisional(self, client, db):
        arrive = today_utc() + timedelta(days=3)
        trip = make_trip(client, arrive_date=arrive.isoformat(),
                         depart_date=(arrive + timedelta(days=1)).isoformat())
        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["provisional"] == []

    def test_past_a_week_out_only_regular_hours_are_knowable(self, client, db):
        trip = make_trip(client)  # 30 days out
        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["provisional"] == [REGULAR_HOURS_ONLY_NOTE]

    def test_beyond_the_transit_horizon_it_is_walking_only_as_well(self, client, db):
        arrive = today_utc() + timedelta(days=200)
        trip = make_trip(client, arrive_date=arrive.isoformat(),
                         depart_date=(arrive + timedelta(days=2)).isoformat())
        body = client.post(f"/trips/{trip}/days/0/route", json={}).json()
        assert body["provisional"] == [TRANSIT_HORIZON_NOTE, REGULAR_HOURS_ONLY_NOTE]


def test_health_needs_no_database(client):
    assert client.get("/health").json() == {"status": "ok"}
