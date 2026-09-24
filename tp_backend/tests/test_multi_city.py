"""A trip covering several cities: one run per city, one shortlist, one draft at the end."""

from datetime import UTC, date, datetime, timedelta

from conftest import HELSINKI, make_city, make_mention, make_place, make_trip, plan_body
from sqlalchemy import select, update

from libs.db import (
    City,
    IngestRun,
    IngestTask,
    Place,
    PlaceHours,
    PlaceQuery,
    Trip,
    TripCity,
    TripPlace,
    UserTrip,
    YouTubeVideo,
    claim_for_city_trips,
)
from libs.db.enums import Confidence, RunKind, RunStatus, Source, TaskKind, TripRole
from libs.ingest import latest_runs, plan_after_ingest
from libs.places import CityDetails, VenueHit
from tp_api.deps import venue_lookup
from tp_api.main import app
from tp_api.route_planning.service import first_daylight, shortlist, sun_by_place
from tp_api.schemas import MAX_TRIP_CITIES, today_utc
from tp_ingestions.plan import draft
from tp_ingestions.plan.draft import render
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.youtube import extract

PORTO = "ChIJraHNsVNlJA0R-2sVTNTODlM"

DETAILS = {
    HELSINKI: CityDetails(place_id=HELSINKI, name="Helsinki", country="FI",
                          timezone="Europe/Helsinki", lat=60.17, lon=24.94),
    PORTO: CityDetails(place_id=PORTO, name="Porto", country="PT", timezone="Europe/Lisbon",
                       lat=41.15, lon=-8.61),
}


def two_cities(lookup, city_place_ids=(HELSINKI, PORTO), **kw):
    lookup["fn"] = lambda place_id: DETAILS[place_id]
    return plan_body(city_place_ids=list(city_place_ids), **kw)


def settle(db, city_id, status=RunStatus.DONE):
    run_id = db.scalar(
        select(IngestRun.run_id).where(IngestRun.city_id == city_id,
                                       IngestRun.kind == "city_ingest")
    )
    db.execute(update(IngestRun).where(IngestRun.run_id == run_id).values(status=status))
    db.commit()
    plan_after_ingest(db, run_id)
    db.commit()
    return run_id


VIDEO = "VpkCSDYVaRc"


def extract_task(run_id, city_id):
    return ClaimedTask(task_id=1, run_id=run_id, kind=TaskKind.YOUTUBE_EXTRACT,
                       source=Source.YOUTUBE, payload={"video_id": VIDEO, "city_id": city_id},
                       attempts=1, max_attempts=5)


def drafts(db, trip_id):
    return db.scalars(
        select(IngestTask.task_id).where(IngestTask.kind == TaskKind.ROUTE_PLAN,
                                         IngestTask.payload["trip_id"].astext == trip_id)
    ).all()


def test_each_city_gets_its_own_run_and_seed_tasks(client, db, lookup):
    body = client.post("/initiate-plan", json=two_cities(lookup)).json()

    assert [c["name"] for c in body["cities"]] == ["Helsinki", "Porto"]
    assert body["city"]["name"] == "Helsinki"
    assert set(db.scalars(select(TripCity.city_id))) == {HELSINKI, PORTO}
    assert set(db.scalars(select(IngestRun.city_id))) == {HELSINKI, PORTO}
    assert len(db.scalars(select(IngestTask.task_id)).all()) == 6


def test_a_city_named_twice_is_one_city(client, db, lookup):
    body = client.post("/initiate-plan",
                       json=two_cities(lookup, [HELSINKI, PORTO, HELSINKI])).json()

    assert [c["city_id"] for c in body["cities"]] == [HELSINKI, PORTO]
    assert len(db.scalars(select(IngestRun.run_id)).all()) == 2


def test_two_aliases_for_one_city_are_one_city(client, db, lookup):
    lookup["fn"] = lambda place_id: DETAILS[HELSINKI if place_id == "hel-alias" else place_id]

    body = client.post("/initiate-plan",
                       json=plan_body(city_place_ids=[HELSINKI, "hel-alias"])).json()

    assert [c["city_id"] for c in body["cities"]] == [HELSINKI]
    assert set(db.scalars(select(TripCity.city_id))) == {HELSINKI}


def test_the_cities_are_anchor_first_even_when_the_anchor_sorts_last(client, db, lookup):
    created = client.post("/initiate-plan", json=two_cities(lookup, [PORTO, HELSINKI])).json()
    trip_id = created["trip_id"]

    assert [c["city_id"] for c in created["cities"]] == [PORTO, HELSINKI]
    assert [c["city_id"] for c in client.get(f"/trips/{trip_id}").json()["cities"]] \
        == [PORTO, HELSINKI]
    assert [c["city_id"] for c in client.get("/trips").json()[0]["cities"]] == [PORTO, HELSINKI]


def test_a_trip_lists_even_if_it_does_not_cover_its_own_anchor(client, db):
    make_city(db)
    make_city(db, city_id=PORTO, name="Porto")
    trip_id = make_trip(db, "t-odd", city_ids=(HELSINKI, PORTO))
    db.execute(TripCity.__table__.delete().where(TripCity.city_id == HELSINKI))
    db.add(UserTrip(user_id="u-test", trip_id=trip_id, role=TripRole.OWNER))
    db.commit()

    rows = client.get("/trips").json()

    assert [t["city"]["city_id"] for t in rows] == [HELSINKI]


def test_every_city_warm_ingests_nothing_and_drafts_once(client, db, lookup):
    make_city(db, last_ingested_at=datetime.now(UTC))
    make_city(db, city_id=PORTO, name="Porto", last_ingested_at=datetime.now(UTC))

    body = client.post("/initiate-plan", json=two_cities(lookup)).json()

    assert body["ingest"] is None
    assert db.scalars(select(IngestRun.kind)).all() == [RunKind.TRIP_PLANNING]
    assert len(drafts(db, body["trip_id"])) == 1
    got = client.get(f"/trips/{body['trip_id']}").json()
    assert got["ingest"] is None
    assert [(p["kind"], p["status"]) for p in got["progress"]] \
        == [(TaskKind.ROUTE_PLAN, "pending")]


def test_two_cities_sharing_a_language_still_get_distinct_seed_tasks(client, db, lookup):
    lisbon = "ChIJO_PkYRXKAQ0Ra7VLZjNNwie"
    DETAILS[lisbon] = CityDetails(place_id=lisbon, name="Lisbon", country="PT",
                                  timezone="Europe/Lisbon", lat=38.72, lon=-9.14)

    client.post("/initiate-plan", json=two_cities(lookup, [PORTO, lisbon]))

    keys = db.scalars(select(IngestTask.dedupe_key)).all()
    assert len(set(keys)) == len(keys) == 6


def test_a_trip_takes_at_least_one_city_and_at_most_the_cap(client, lookup):
    lookup["fn"] = lambda place_id: DETAILS[HELSINKI]
    assert client.post("/initiate-plan", json=plan_body(city_place_ids=[])).status_code == 422
    too_many = [f"c{i}" for i in range(MAX_TRIP_CITIES + 1)]
    assert client.post("/initiate-plan",
                       json=plan_body(city_place_ids=too_many)).status_code == 422


def test_a_place_resolved_in_one_city_is_claimed_by_a_trip_anchored_in_another(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    db.add(Place(place_id="porto-1", city_id=PORTO, name="Bolhão", confidence=Confidence.HIGH))
    db.flush()
    claim_for_city_trips(db, PORTO, ["porto-1"])
    db.commit()

    assert set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id))) \
        == {"porto-1"}


def test_the_shortlist_is_the_union_of_every_city(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hel-1")
    make_place(db, city_id=PORTO, place_id="por-1")

    got = client.get(f"/trips/{trip_id}/shortlist").json()

    assert {p["place_id"] for p in got["places"]} == {"hel-1", "por-1"}


def test_a_trip_is_not_settled_until_every_city_is(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI)
    mid = client.get(f"/trips/{trip_id}").json()
    assert mid["ingest"]["status"] == RunStatus.PENDING, "Porto is still outstanding"

    settle(db, PORTO)
    end = client.get(f"/trips/{trip_id}").json()
    assert end["ingest"]["status"] == RunStatus.DONE


def test_progress_is_summed_across_the_cities(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    progress = client.get(f"/trips/{trip_id}").json()["progress"]

    counts = {(p["kind"], p["status"]): p["count"] for p in progress}
    assert counts[(TaskKind.YOUTUBE_SEARCH, "pending")] == 4, "two cities, two languages each"
    assert counts[(TaskKind.REDNOTE_SEARCH, "pending")] == 2


def test_a_warm_city_is_nothing_to_wait_for(client, db, lookup):
    make_city(db, city_id=PORTO, name="Porto", last_ingested_at=datetime.now(UTC))
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    assert set(db.scalars(select(IngestRun.city_id))) == {HELSINKI}, "only the cold city runs"
    assert drafts(db, trip_id) == [], "one city is still cold, so nothing to draft from yet"

    settle(db, HELSINKI)

    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] == RunStatus.DONE
    assert len(drafts(db, trip_id)) == 1


def test_the_draft_waits_for_the_last_city_and_happens_once(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI)
    assert drafts(db, trip_id) == [], "Porto's places would have been missing from this draft"

    settle(db, PORTO)
    assert len(drafts(db, trip_id)) == 1


def test_one_failed_city_does_not_cost_the_trip_its_draft(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI, status=RunStatus.FAILED)
    settle(db, PORTO)

    assert len(drafts(db, trip_id)) == 1, "Porto succeeded, so there is a shortlist to draft"
    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] == RunStatus.DONE


def test_every_city_failing_is_terminal_with_no_draft(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI, status=RunStatus.FAILED)
    settle(db, PORTO, status=RunStatus.FAILED)

    assert drafts(db, trip_id) == [], "nothing was ingested, so there is nothing to arrange"
    status = client.get(f"/trips/{trip_id}").json()["ingest"]["status"]
    assert status == RunStatus.FAILED, "terminal, so the client stops polling"


def test_a_failed_city_still_claims_nothing_but_leaves_the_others_intact(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hel-1")

    settle(db, PORTO, status=RunStatus.FAILED)

    assert set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id))) \
        == {"hel-1"}


def test_the_trips_list_sums_both_cities(client, db, lookup):
    client.post("/initiate-plan", json=two_cities(lookup))

    row = client.get("/trips").json()[0]

    assert [c["name"] for c in row["cities"]] == ["Helsinki", "Porto"]
    assert row["tasks_total"] == 6, "both cities' tasks, not just the anchor's"
    assert row["ingest"]["status"] == RunStatus.PENDING


def test_a_deleted_trip_is_not_claimed_for(db):
    make_city(db)
    make_city(db, city_id=PORTO, name="Porto")
    live = make_trip(db, "t-live", city_ids=(HELSINKI, PORTO))
    make_trip(db, "t-gone", city_ids=(HELSINKI, PORTO), deleted=True)
    db.add(Place(place_id="por-1", city_id=PORTO, name="Bolhão", confidence=Confidence.HIGH))
    db.flush()

    claim_for_city_trips(db, PORTO, ["por-1"])
    db.commit()

    assert set(db.scalars(select(TripPlace.trip_id))) == {live}


def test_a_trip_predating_trip_cities_still_reads(client, db):
    make_city(db)
    trip_id = make_trip(db, "t-old")
    db.execute(TripCity.__table__.delete().where(TripCity.trip_id == trip_id))
    db.add(UserTrip(user_id="u-test", trip_id=trip_id, role=TripRole.OWNER))
    db.commit()

    assert client.get(f"/trips/{trip_id}").status_code == 200
    assert [t["trip_id"] for t in client.get("/trips").json()] == [trip_id]


def test_the_draft_still_fires_when_the_last_city_is_the_one_that_failed(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI)
    settle(db, PORTO, status=RunStatus.FAILED)

    assert len(drafts(db, trip_id)) == 1
    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] == RunStatus.DONE


def test_a_city_wanting_credentials_is_not_hidden_behind_one_that_worked(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    settle(db, HELSINKI)
    settle(db, PORTO, status=RunStatus.NEEDS_CREDENTIALS)

    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] \
        == RunStatus.NEEDS_CREDENTIALS
    assert len(drafts(db, trip_id)) == 1, "Helsinki still gave the trip something to arrange"


def test_drafting_by_hand_mid_ingestion_does_not_consume_the_automatic_draft(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    settle(db, HELSINKI)

    assert client.post(f"/trips/{trip_id}/draft").status_code == 202
    assert len(drafts(db, trip_id)) == 1, "the user's own draft, off a half-built shortlist"

    settle(db, PORTO)

    assert len(drafts(db, trip_id)) == 2, "Porto's places still get a draft of their own"


def test_settling_one_city_claims_places_filed_under_another(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    settle(db, HELSINKI)
    db.execute(TripPlace.__table__.delete())
    db.add(Place(place_id="late", city_id=HELSINKI, name="Late", confidence=Confidence.HIGH))
    db.commit()

    settle(db, PORTO)

    assert set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id))) \
        == {"late"}


def test_an_active_run_outranks_a_settled_one_made_in_the_same_transaction(db):
    make_city(db)
    db.add(IngestRun(run_id="r-old", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                     status=RunStatus.FAILED))
    db.add(IngestRun(run_id="r-new", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                     status=RunStatus.PENDING))
    db.commit()

    assert latest_runs(db, [HELSINKI])[HELSINKI].run_id == "r-new"


def test_a_source_naming_two_cities_is_resolved_against_each(db, monkeypatch):
    make_city(db)
    make_city(db, city_id=PORTO, name="Porto")
    for run_id, city_id in (("r-hel", HELSINKI), ("r-por", PORTO)):
        db.add(IngestRun(run_id=run_id, city_id=city_id, kind=RunKind.CITY_INGEST,
                         status=RunStatus.RUNNING))
    db.add(YouTubeVideo(video_id=VIDEO, title="Helsinki and Porto", channel="ch",
                        transcript="Löyly in Helsinki, then Bolhão in Porto"))
    db.commit()
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: {
        "is_travel_content": True, "content_type": "travel guide", "city": "Helsinki",
        "city_confidence": "high",
        "places": [{"name": "Löyly", "name_confidence": "high", "category": "do",
                    "timestamp": "04:12", "why_go": "a sauna", "sentiment": "recommended"}]})

    first = extract.youtube_extract(db, extract_task("r-hel", HELSINKI))
    db.commit()
    second = extract.youtube_extract(db, extract_task("r-por", PORTO))
    db.commit()

    assert first["resolve_queued"] == 1
    assert second == {"video_id": VIDEO, "cached": True, "resolve_queued": 1}
    assert set(db.scalars(
        select(IngestTask.run_id).where(IngestTask.kind == TaskKind.PLACES_RESOLVE)
    )) == {"r-hel", "r-por"}, "one resolve per city, off the one stored extraction"


def midsummer() -> date:
    now = today_utc()
    return date(now.year + (1 if now > date(now.year, 6, 21) else 0), 6, 21)


def far_apart(client, db, lookup):
    arrive = midsummer()
    trip_id = client.post("/initiate-plan", json=two_cities(
        lookup, arrive_date=arrive.isoformat(), arrive_time=None,
        depart_date=(arrive + timedelta(days=1)).isoformat())).json()["trip_id"]
    for place_id, city_id, name, lat, lon in (
        ("hel", HELSINKI, "Suomenlinna", 60.14, 24.98),
        ("por", PORTO, "Jardim do Morro", 41.14, -8.61),
    ):
        make_place(db, city_id=city_id, place_id=place_id, name=name, lat=lat, lon=lon)
        make_mention(db, place_id, category="see")
    client.put(f"/trips/{trip_id}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "hel", "start_min": 21 * 60 + 30, "duration_min": 60},
        {"place_id": "por", "start_min": 21 * 60 + 30, "duration_min": 60}]}]})
    return trip_id


def test_each_block_is_judged_against_its_own_city_s_sunset(client, db, lookup, hours):
    trip_id = far_apart(client, db, lookup)

    body = client.post(f"/trips/{trip_id}/days/0/route", json={}).json()

    assert [w["place_id"] for w in body["warnings"] if w["code"] == "after_sunset"] == ["por"]
    assert body["daylight"]["sunset"] > "22:00", "Helsinki's, not Porto's"


def test_the_shortlist_says_which_city_each_place_is_in(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hel")
    make_place(db, city_id=PORTO, place_id="por")

    places = client.get(f"/trips/{trip_id}/shortlist").json()["places"]

    assert {p["place_id"]: p["city_id"] for p in places} == {"hel": HELSINKI, "por": PORTO}


def test_the_draft_prompt_places_each_city_and_measures_from_its_own_centre(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hel", name="Löyly", lat=60.15, lon=24.93)
    make_place(db, city_id=PORTO, place_id="por", name="Bolhão", lat=41.15, lon=-8.61)
    trip = db.get(Trip, trip_id)
    places = shortlist(db, trip_id, 40, 0, None).places

    prompt = render(db, trip, places, [0])

    assert "Helsinki, FI and Porto, PT" in prompt
    por = next(ln for ln in prompt.splitlines() if "Bolhão" in ln)
    assert "Porto" in por and "0.0km" in por, por
    day = next(ln for ln in prompt.splitlines() if ln.startswith("day 0"))
    assert "Helsinki sunrise" in day and "Porto sunrise" in day, day


def test_a_hand_added_place_is_still_judged_against_the_daylight(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=HELSINKI, place_id="hand", name="A Viewpoint", category="see")
    client.put(f"/trips/{trip_id}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "hand", "start_min": 23 * 60, "duration_min": 30}]}]})

    body = client.post(f"/trips/{trip_id}/days/0/route", json={}).json()

    assert "after_sunset" in [w["code"] for w in body["warnings"]]


def test_a_hand_added_place_is_filed_under_the_nearest_city_it_could_be_in(client, db, lookup):
    arrive = midsummer()
    trip_id = client.post("/initiate-plan", json=two_cities(
        lookup, arrive_date=arrive.isoformat(), arrive_time=None,
        depart_date=(arrive + timedelta(days=1)).isoformat())).json()["trip_id"]
    app.dependency_overrides[venue_lookup] = lambda: (lambda pid: VenueHit(
        place_id="por", name="Jardim do Morro", address="Porto", lat=41.1375, lon=-8.6094,
        rating=4.7, rating_count=900, primary_type="Park", types=["park"]))

    client.post(f"/trips/{trip_id}/places", json={"place_id": "por", "category": "see"})

    assert db.get(Place, "por").city_id == PORTO
    client.put(f"/trips/{trip_id}/itinerary", json={"days": [{"day_index": 0, "items": [
        {"place_id": "por", "start_min": 22 * 60, "duration_min": 30}]}]})
    body = client.post(f"/trips/{trip_id}/days/0/route", json={}).json()
    assert [w["place_id"] for w in body["warnings"] if w["code"] == "after_sunset"] == ["por"]


def test_the_day_s_window_is_the_first_block_that_has_one():
    assert first_daylight({"b": (300.0, 1200.0)}, ["a", "b"]) == (300.0, 1200.0)
    assert first_daylight({}, ["a"]) == (None, None)


def test_a_place_with_no_coordinates_is_not_drafted_as_central(client, db, lookup):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    make_place(db, city_id=PORTO, place_id="por", name="No Coords", lat=None, lon=None)
    trip = db.get(Trip, trip_id)

    prompt = render(db, trip, shortlist(db, trip_id, 40, 0, None).places, [0])

    assert "No Coords | - | Porto | ?km" in prompt


def test_a_thin_city_is_not_crowded_out_of_the_draft(client, db, lookup, monkeypatch):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    monkeypatch.setattr(draft, "LIMIT", 2)
    for i in range(2):
        make_place(db, place_id=f"h{i}", name=f"Helsinki {i}")
        for ref in ("a", "b"):
            make_mention(db, f"h{i}", source_ref=ref)
    make_place(db, city_id=PORTO, place_id="por", name="Bolhão")
    make_mention(db, "por", source_ref="c")
    prompts = []
    monkeypatch.setattr(draft, "generate",
                        lambda _prompt, rendered: prompts.append(rendered) or {"days": []})

    draft.run(db, ClaimedTask(task_id=1, run_id="r", kind=TaskKind.ROUTE_PLAN, source=None,
                              payload={"trip_id": trip_id}, attempts=1, max_attempts=3))

    assert "Bolhão" in prompts[0]


def test_a_trip_created_later_claims_a_place_its_city_resolved_under_another_city(client, db, lookup):
    make_city(db, city_id=PORTO, name="Porto")
    make_city(db, city_id="lisbon", name="Lisbon")
    make_place(db, city_id="lisbon", place_id="por", name="Bolhão")
    db.add(PlaceQuery(city_id=PORTO, query_norm="bolhão, porto", place_id="por"))
    db.commit()

    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    places = client.get(f"/trips/{trip_id}/shortlist").json()["places"]
    assert [p["place_id"] for p in places] == ["por"]


def test_a_city_with_no_zone_gives_all_its_places_one_window(db):
    make_city(db)
    db.execute(update(City).where(City.city_id == HELSINKI).values(timezone=None))
    for place_id in ("a", "b"):
        make_place(db, place_id=place_id, lat=60.17, lon=24.94)
    places = list(db.scalars(select(Place).where(Place.place_id.in_(["a", "b"]))))

    sun = sun_by_place(db, places, midsummer(),
                       {"a": PlaceHours(place_id="a", utc_offset_minutes=180)})

    assert sun["a"] == sun["b"] != (None, None)
