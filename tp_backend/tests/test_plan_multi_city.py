"""Planning a trip that covers two cities far apart: one shortlist, one day, one draft, one workbook."""

from datetime import timedelta
from io import BytesIO

from conftest import HELSINKI, make_mention, make_place
from openpyxl import load_workbook
from sqlalchemy import select
from test_multi_city import PORTO, a_future_date, two_cities

from libs.db import City, ItineraryItem, Place, Trip, TripPlace
from libs.db.enums import Confidence, TaskKind
from libs.routing import HoursHit
from tp_api.route_planning.service import shortlist
from tp_api.route_planning.utils import google_weekday
from tp_ingestions.plan import draft
from tp_ingestions.queue import ClaimedTask

SINGAPORE = "ChIJdZOLiiMR2jERnbSmdlpEFRI"


def two_city_trip(client, lookup, days=1, **kw):
    arrive = a_future_date()
    return client.post("/initiate-plan", json=two_cities(
        lookup, arrive_date=arrive.isoformat(), arrive_time=None, depart_time=None,
        depart_date=(arrive + timedelta(days=days)).isoformat(), **kw)).json()["trip_id"]


def pin(client, trip, items, day=0):
    r = client.put(f"/trips/{trip}/itinerary", json={"days": [{"day_index": day, "items": items}]})
    assert r.status_code == 200, r.text
    return r.json()


def block(place_id, start_min, duration_min=60, **kw):
    return {"place_id": place_id, "start_min": start_min, "duration_min": duration_min} | kw


def open_until(hour):
    return lambda ids: {i: HoursHit(place_id=i, periods=[
        {"open": {"day": d, "hour": 8, "minute": 0},
         "close": {"day": d, "hour": hour, "minute": 0}} for d in range(7)],
        weekday_descriptions=[], utc_offset_minutes=60) for i in ids}


def one_in_each_city(db, trip, hel_start, por_start):
    make_place(db, city_id=HELSINKI, place_id="hel", name="Suomenlinna", lat=60.14, lon=24.98)
    make_mention(db, "hel", category="see")
    make_place(db, city_id=PORTO, place_id="por", name="Jardim do Morro", lat=41.15, lon=-8.61)
    make_mention(db, "por", category="see", source_ref="ref2")
    return [block("por", por_start), block("hel", hel_start)]


def test_the_ranking_ignores_which_city_a_place_is_in(client, db, lookup):
    trip = two_city_trip(client, lookup)
    make_place(db, city_id=HELSINKI, place_id="hel", name="Once named")
    make_mention(db, "hel")
    make_place(db, city_id=PORTO, place_id="por", name="Thrice named")
    for i in range(3):
        make_mention(db, "por", source_ref=f"por-{i}")

    places = client.get(f"/trips/{trip}/shortlist").json()["places"]

    assert [(p["name"], p["city_name"]) for p in places] == [("Thrice named", "Porto"),
                                                             ("Once named", "Helsinki")]


def test_a_day_mixing_two_cities_draws_no_complaint(client, db, lookup, hours):
    trip = two_city_trip(client, lookup)
    hours["fn"] = open_until(23)

    pin(client, trip, one_in_each_city(db, trip, hel_start=13 * 60, por_start=12 * 60))
    body = client.post(f"/trips/{trip}/days/0/route", json={}).json()

    assert [b["place_id"] for b in body["blocks"]] == ["por", "hel"]
    assert body["warnings"] == []


def singapore_place(db, trip):
    db.add(City(city_id=SINGAPORE, name="Singapore", country="SG", timezone="Asia/Singapore",
                lat=1.35, lon=103.82))
    db.add(Place(place_id="sgp", city_id=SINGAPORE, name="Gardens by the Bay", lat=1.28, lon=103.86,
                 confidence=Confidence.HIGH, category="see"))
    db.flush()
    db.add(TripPlace(trip_id=trip, place_id="sgp"))
    db.commit()


def test_the_draft_prompt_names_a_city_the_trip_does_not_cover(client, db, lookup):
    trip = two_city_trip(client, lookup)
    singapore_place(db, trip)

    prompt = draft.render(db, db.get(Trip, trip), shortlist(db, trip, 40, 0, None).places, [0])

    row = next(ln for ln in prompt.splitlines() if "Gardens by the Bay" in ln)
    assert "Singapore" in row and "0.0km" not in row, row


def test_more_stored_stops_than_a_day_takes_is_a_422(client, db, lookup):
    trip = two_city_trip(client, lookup)
    for i in range(26):
        make_place(db, city_id=PORTO if i % 2 else HELSINKI, place_id=f"p{i}", name=f"Place {i}")
        db.add(ItineraryItem(trip_id=trip, place_id=f"p{i}", day_index=0,
                             start_min=8 * 60 + i * 30, duration_min=30))
    db.commit()

    assert client.post(f"/trips/{trip}/days/0/route", json={}).status_code == 422


def workbook(client, trip):
    r = client.get(f"/trips/{trip}/export.xlsx")
    assert r.status_code == 200, r.text
    return load_workbook(BytesIO(r.content))["Itinerary"]


def a_two_city_day(client, db, lookup, **kw):
    trip = two_city_trip(client, lookup, days=1)
    items = one_in_each_city(db, trip, hel_start=13 * 60, por_start=12 * 60)
    pin(client, trip, [items[0], items[1] | kw])
    return trip


def test_the_export_bands_each_day(client, db, lookup):
    trip = a_two_city_day(client, db, lookup)

    ws = workbook(client, trip)

    assert ws.cell(row=4, column=1).value == f"Day 1 · {a_future_date():%a %d %b}"
    assert ws.cell(row=7, column=1).value.startswith("Day 2 · ")


def test_the_ref_column_marks_only_the_block_that_carries_a_link(client, db, lookup):
    trip = a_two_city_day(client, db, lookup,
                          reference_url="https://www.airbnb.com/rooms/12345")

    ws = workbook(client, trip)

    shown = [c.value for c in ws[3] if not ws.column_dimensions[c.column_letter].hidden]
    assert shown[-1] == "Ref"
    assert ws.cell(row=5, column=8).value is None, "Porto has no link of its own"
    assert ws.cell(row=6, column=8).hyperlink.target == "https://www.airbnb.com/rooms/12345"


def drivable(client, db, lookup, monkeypatch, reply, hours_for):
    trip = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hel", name="Löyly")
    for i in range(2):
        make_mention(db, "hel", category="do", source_ref=f"hel-{i}")
    make_place(db, city_id=PORTO, place_id="por", name="Bolhão")
    make_mention(db, "por", category="eat", source_ref="por-0")

    calls = []
    monkeypatch.setattr(draft, "generate", lambda prompt, text: calls.append(text) or reply)
    monkeypatch.setattr(draft, "fetch_hours", hours_for)
    return trip, calls


def periods(days, open_hour=8, close_hour=23):
    return [{"open": {"day": d, "hour": open_hour, "minute": 0},
             "close": {"day": d, "hour": close_hour, "minute": 0}} for d in days]


def hours_of(per_place):
    return lambda ids: {i: HoursHit(place_id=i, periods=per_place(i), weekday_descriptions=[],
                                    utc_offset_minutes=180) for i in ids}


def task(trip):
    return ClaimedTask(task_id=1, run_id="r-plan", kind=TaskKind.ROUTE_PLAN, source=None,
                       payload={"trip_id": trip}, attempts=1, max_attempts=3)


BOTH = {"days": [{"day": 0, "picks": [{"index": 0, "start_min": 900, "duration_min": 60},
                                      {"index": 1, "start_min": 1080, "duration_min": 60}]}]}


def test_the_draft_lands_blocks_from_both_cities(client, db, lookup, monkeypatch):
    trip, calls = drivable(client, db, lookup, monkeypatch, BOTH,
                           hours_of(lambda i: periods(range(7))))

    assert draft.run(db, task(trip)) == {"days": 1, "blocks": 2, "rounds": 1, "unresolved": 0}
    assert len(calls) == 1
    assert set(db.scalars(select(ItineraryItem.place_id))) == {"hel", "por"}
    assert "Bolhão" in calls[0] and "Löyly" in calls[0]


def test_the_draft_drops_a_place_proven_closed_all_day(client, db, lookup, monkeypatch):
    trip, calls = drivable(client, db, lookup, monkeypatch, BOTH, hours_of(
        lambda i: periods(range(7))))
    tomorrow = (google_weekday(db.get(Trip, trip).arrive_date) + 1) % 7
    monkeypatch.setattr(draft, "fetch_hours", hours_of(
        lambda i: periods([tomorrow] if i == "por" else range(7))))

    result = draft.run(db, task(trip))

    assert result == {"days": 1, "blocks": 1, "rounds": 2, "unresolved": 0}
    assert len(calls) == 2, "one retry, with the closed place named in the feedback"
    assert db.scalars(select(ItineraryItem.place_id)).all() == ["hel"]


def test_a_draft_with_nothing_shortlisted_spends_no_model_call(client, db, lookup, monkeypatch):
    trip = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    monkeypatch.setattr(draft, "generate", lambda *a: 1 / 0)

    assert draft.run(db, task(trip)) == {"skipped": draft.NO_PLACES}


FLIGHT = {"kind": "custom", "block_id": "b-flight", "title": "Flight", "start_min": 600,
          "duration_min": 60}
TWO_DAYS = {"days": [{"day": 0, "picks": [{"index": 0, "start_min": 900, "duration_min": 60}]},
                     {"day": 1, "picks": [{"index": 1, "start_min": 720, "duration_min": 60}]}]}


def itinerary(db):
    return {(r.day_index, r.place_id, r.title)
            for r in db.execute(select(ItineraryItem.day_index, ItineraryItem.place_id,
                                       ItineraryItem.title))}


def test_a_draft_leaves_a_flight_only_day_alone(client, db, lookup, monkeypatch):
    trip, _ = drivable(client, db, lookup, monkeypatch, TWO_DAYS,
                       hours_of(lambda i: periods(range(7))))
    pin(client, trip, [FLIGHT], day=1)

    assert draft.run(db, task(trip))["days"] == 1
    assert itinerary(db) == {(0, "hel", None), (1, None, "Flight")}


def test_a_day_filled_while_the_model_thinks_is_left_alone(client, db, lookup, monkeypatch):
    trip, _ = drivable(client, db, lookup, monkeypatch, TWO_DAYS,
                       hours_of(lambda i: periods(range(7))))
    monkeypatch.setattr(draft, "generate",
                        lambda prompt, text: pin(client, trip, [FLIGHT], day=1) and TWO_DAYS)

    out = draft.run(db, task(trip))

    assert out["filled_meanwhile"] == [1]
    assert itinerary(db) == {(0, "hel", None), (1, None, "Flight")}


def test_a_day_keeps_the_city_it_was_put_in(client, db, lookup):
    trip = two_city_trip(client, lookup, days=2)

    pin_day = {"days": [{"day_index": 1, "city_id": PORTO, "items": []}]}
    days = client.put(f"/trips/{trip}/itinerary", json=pin_day).json()["days"]
    assert [d["city_id"] for d in days][:2] == [None, PORTO]

    pin(client, trip, [], day=1)
    assert client.get(f"/trips/{trip}/itinerary").json()["days"][1]["city_id"] == PORTO, \
        "a day sent without city_id keeps its city"

    unset = {"days": [{"day_index": 1, "city_id": None, "items": []}]}
    assert client.put(f"/trips/{trip}/itinerary", json=unset).json()["days"][1]["city_id"] is None


def test_a_day_cannot_be_put_in_a_city_the_trip_does_not_cover(client, db, lookup):
    trip = two_city_trip(client, lookup)
    singapore_place(db, trip)

    r = client.put(f"/trips/{trip}/itinerary",
                   json={"days": [{"day_index": 0, "city_id": SINGAPORE, "items": []}]})
    assert r.status_code == 422


def test_the_draft_keeps_a_city_day_to_that_city(client, db, lookup, monkeypatch):
    trip, calls = drivable(client, db, lookup, monkeypatch, BOTH,
                           hours_of(lambda i: periods(range(7))))
    client.put(f"/trips/{trip}/itinerary",
               json={"days": [{"day_index": 0, "city_id": PORTO, "items": []}]})

    assert draft.run(db, task(trip))["blocks"] == 1
    assert db.scalars(select(ItineraryItem.place_id)).all() == ["por"]
    assert "in Porto only" in calls[0]


def test_the_shortlist_search_matches_name_address_and_why_go(client, db, lookup):
    trip = two_city_trip(client, lookup)
    make_place(db, city_id=HELSINKI, place_id="a", name="Löyly", address="Hernesaarenranta 4")
    make_mention(db, "a")
    make_place(db, city_id=PORTO, place_id="b", name="Bolhão")
    make_mention(db, "b", source_ref="r2", why_go="the best 100%_sauna fish")

    def names(q):
        return [p["name"] for p in
                client.get(f"/trips/{trip}/shortlist", params={"q": q}).json()["places"]]

    assert names("löy") == ["Löyly"]
    assert names("HERNES") == ["Löyly"]
    assert names("100%_") == ["Bolhão"]
    assert names("B%o") == []
    assert sorted(names("  ")) == ["Bolhão", "Löyly"]
