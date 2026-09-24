"""The whole pipeline for a trip covering two cities: one run each, one worker, one draft."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import HELSINKI, make_city, plan_body
from sqlalchemy import select, update

from libs import gemini
from libs.db import IngestRun, IngestTask, Place, RedNotePost, TripPlace
from libs.db.enums import ErrorCode, RunKind, RunStatus, TaskKind, TaskStatus
from libs.places import CityDetails, VenueHit
from libs.prompts import REDNOTE_TEXT, YOUTUBE_TRANSCRIPT
from tp_ingestions.errors import TaskError, Throttled
from tp_ingestions.places import resolve as places_resolve
from tp_ingestions.plan import draft
from tp_ingestions.rednote import client as rednote_client
from tp_ingestions.throttle import Throttler
from tp_ingestions.worker import Worker
from tp_ingestions.youtube import client as youtube_client
from tp_ingestions.youtube import extract as youtube_extract

PORTO = "ChIJraHNsVNlJA0R-2sVTNTODlM"
LISBON = "ChIJO_PkYRXKAQ0Ra7VLZjNNwie"

DETAILS = {
    HELSINKI: CityDetails(place_id=HELSINKI, name="Helsinki", country="FI",
                          timezone="Europe/Helsinki", lat=60.17, lon=24.94),
    PORTO: CityDetails(place_id=PORTO, name="Porto", country="PT", timezone="Europe/Lisbon",
                       lat=41.15, lon=-8.61),
}

KAUPPAHALLI, BOLHAO = "Vanha Kauppahalli", "Bolhão"

VENUES = {
    f"{KAUPPAHALLI}, Helsinki": VenueHit(
        place_id="pid-kauppahalli", name="Old Market Hall", address="Etelaranta",
        lat=60.166, lon=24.951, rating=4.5, rating_count=8000,
        primary_type="Market", types=["tourist_attraction"]),
    f"{BOLHAO}, Porto": VenueHit(
        place_id="pid-bolhao", name="Mercado do Bolhão", address="Rua Formosa",
        lat=41.149, lon=-8.606, rating=4.3, rating_count=9000,
        primary_type="Market", types=["tourist_attraction"]),
}

HEL_VIDEO, POR_VIDEO, BOTH_VIDEO = "helvid00001", "porvid00001", "bothvid0001"
HEL_NOTE, POR_NOTE, BOTH_NOTE = "hel" + "0" * 21, "por" + "0" * 21, "both" + "0" * 20

VIDEOS = {
    HEL_VIDEO: (f"welcome to Helsinki, go to {KAUPPAHALLI}", ("Helsinki",)),
    POR_VIDEO: (f"welcome to Porto, go to {BOLHAO}", ("Porto",)),
    BOTH_VIDEO: (f"{KAUPPAHALLI} in Helsinki, then {BOLHAO} in Porto", ("Helsinki", "Porto")),
}

NOTES = {
    HEL_NOTE: (f"{KAUPPAHALLI} 很好吃", ("Helsinki",)),
    POR_NOTE: (f"{BOLHAO} 很好吃", ("Porto",)),
    BOTH_NOTE: (f"{KAUPPAHALLI} and {BOLHAO}", ("Helsinki", "Porto")),
}


def two_cities(lookup, city_place_ids=(HELSINKI, PORTO), **kw):
    lookup["fn"] = lambda place_id: DETAILS[place_id]
    return plan_body(city_place_ids=list(city_place_ids), **kw)


class Calls:

    def __init__(self):
        self.gemini: list[tuple[str, str]] = []
        self.fetch_note: list[str] = []
        self.search_venue: list[str] = []
        self.draft_prompts: list[str] = []

    def prompt(self, version_key: str) -> int:
        return sum(1 for k, _ in self.gemini if k == version_key)


@pytest.fixture
def calls():
    return Calls()


@pytest.fixture
def stubbed(monkeypatch, calls):
    def for_city(q, table):
        city = q.split(" travel")[0].split(" ")[0]
        return [k for k, (_, cities) in table.items() if city in cities]

    monkeypatch.setattr(youtube_client, "search", lambda q, **kw: [
        {"video_id": v, "title": f"{v} travel guide", "channel": "ch",
         "published_at": "2025-01-01T00:00:00Z"} for v in for_city(q, VIDEOS)])
    monkeypatch.setattr(youtube_client, "hydrate", lambda ids: {
        i: {"duration_s": 900, "captions": "MANUAL", "view_count": 50000, "lang": "en",
            "description": "a guide to " + " and ".join(VIDEOS[i][1])} for i in ids})
    monkeypatch.setattr(youtube_extract.tx, "fetch_transcript",
                        lambda vid: [(0.0, VIDEOS[vid][0])])

    monkeypatch.setattr(rednote_client, "search_notes", lambda kw: [
        {"note_id": n, "xsec_token": "tok", "title": "美食", "likes": 196, "author": "a"}
        for n in for_city(kw, NOTES)])

    def fetch_note(note_id, token):
        calls.fetch_note.append(note_id)
        return {"note_id": note_id, "title": "美食", "desc": NOTES[note_id][0],
                "time": 1770919541000, "tag_list": [], "image_list": []}

    monkeypatch.setattr(rednote_client, "fetch_note", fetch_note)

    def search_venue(q, lat, lon, radius):
        calls.search_venue.append(q)
        return VENUES.get(q)

    monkeypatch.setattr(places_resolve, "search_venue", search_venue)

    def generate(prompt, rendered, images=None):
        calls.gemini.append((prompt.version_key, rendered))
        body = rendered.split("</prompt>")[-1]
        found = [n for n in (KAUPPAHALLI, BOLHAO) if n in body]
        if prompt is YOUTUBE_TRANSCRIPT:
            return {"is_travel_content": True, "content_type": "travel guide", "city": "?",
                    "city_confidence": "high",
                    "places": [{"name": n, "name_confidence": "high", "category": "do",
                                "timestamp": "04:12", "why_go": "worth it",
                                "sentiment": "recommended"} for n in found]}
        return {"is_useful": True, "content_type": "food guide", "is_promotional": False,
                "city": "?", "city_confidence": "high",
                "places": [{"name_as_written": n, "name_local": n,
                            "name_local_confidence": "high", "category": "eat",
                            "why_go": "the post rates it", "sentiment": "recommended"}
                           for n in found]}

    monkeypatch.setattr(gemini, "generate", generate)

    def drafted(prompt, rendered, images=None):
        calls.draft_prompts.append(rendered)
        return {"days": []}

    monkeypatch.setattr(draft, "generate", drafted)


def break_cities(monkeypatch, cities, code=ErrorCode.PERMANENT):
    yt, rn = youtube_client.search, rednote_client.search_notes

    def broken(inner):
        def call(q, **kw):
            if any(c in q for c in cities):
                raise TaskError(code, f"broken for {q}")
            return inner(q, **kw)
        return call

    monkeypatch.setattr(youtube_client, "search", broken(yt))
    monkeypatch.setattr(rednote_client, "search_notes", broken(rn))


def run_worker(name="w1"):
    return Worker(name=name, poll_interval=0, reap_interval=1e9).drain()


def tasks(db, kind=None, run_id=None):
    q = select(IngestTask)
    if kind is not None:
        q = q.where(IngestTask.kind == kind)
    if run_id is not None:
        q = q.where(IngestTask.run_id == run_id)
    # Ordered explicitly: an UPDATE leaves dead space a later INSERT reuses, so heap order is not
    # insertion order.
    return db.scalars(q.order_by(IngestTask.task_id)).all()


def city_runs(db):
    return {r.city_id: r for r in db.scalars(
        select(IngestRun).where(IngestRun.kind == RunKind.CITY_INGEST))}


def drafts(db, trip_id):
    return db.scalars(
        select(IngestTask.task_id).where(IngestTask.kind == TaskKind.ROUTE_PLAN,
                                         IngestTask.payload["trip_id"].astext == trip_id)
    ).all()


def claimed(db, trip_id):
    return set(db.scalars(select(TripPlace.place_id).where(TripPlace.trip_id == trip_id)))


def test_both_cities_drain_to_done_in_one_worker_run(client, db, lookup, stubbed):
    client.post("/initiate-plan", json=two_cities(lookup))

    run_worker()

    db.expire_all()
    assert set(db.scalars(select(IngestTask.status))) == {TaskStatus.DONE}
    assert {c: r.status for c, r in city_runs(db).items()} \
        == {HELSINKI: RunStatus.DONE, PORTO: RunStatus.DONE}


def test_both_cities_places_are_claimed_for_the_one_trip(client, db, lookup, stubbed):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    assert claimed(db, trip_id) == {"pid-kauppahalli", "pid-bolhao"}
    assert {p.place_id: p.city_id for p in db.scalars(select(Place))} \
        == {"pid-kauppahalli": HELSINKI, "pid-bolhao": PORTO}


def test_the_drain_drafts_once_and_only_after_the_last_city_settles(client, db, lookup, stubbed):
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    assert len(drafts(db, trip_id)) == 1
    plan = tasks(db, TaskKind.ROUTE_PLAN)[0]
    assert plan.created_at >= max(r.finished_at for r in city_runs(db).values())


def test_the_draft_the_drain_queues_sees_both_cities(client, db, lookup, stubbed, calls):
    client.post("/initiate-plan", json=two_cities(lookup))

    run_worker()

    prompt = calls.draft_prompts[0]
    assert "Helsinki, FI and Porto, PT" in prompt
    assert "Old Market Hall" in prompt and "Mercado do Bolhão" in prompt
    assert "Helsinki sunrise" in prompt and "Porto sunrise" in prompt


def test_a_video_naming_both_cities_is_read_once_and_resolved_per_city(client, db, lookup, stubbed,
                                                                      calls):
    client.post("/initiate-plan", json=two_cities(lookup))

    run_worker()

    db.expire_all()
    assert len(tasks(db, TaskKind.YOUTUBE_EXTRACT)) == 4, "the shared video is claimed by both runs"
    assert calls.prompt(YOUTUBE_TRANSCRIPT.version_key) == 3, "three videos, not four extractions"
    shared = [t for t in tasks(db, TaskKind.PLACES_RESOLVE)
              if t.payload["source_ref"] == BOTH_VIDEO]
    assert {t.payload["city_id"] for t in shared} == {HELSINKI, PORTO}
    assert f"{BOLHAO}, Porto" in calls.search_venue


def test_a_note_naming_both_cities_is_read_once_and_resolved_per_city(client, db, lookup, stubbed,
                                                                     calls):
    client.post("/initiate-plan", json=two_cities(lookup))

    run_worker()

    db.expire_all()
    assert len(tasks(db, TaskKind.REDNOTE_EXTRACT)) == 4
    assert calls.prompt(REDNOTE_TEXT.version_key) == 3, "three notes, not four extractions"
    shared = [t for t in tasks(db, TaskKind.PLACES_RESOLVE)
              if t.payload["source_ref"] == BOTH_NOTE]
    assert {t.payload["city_id"] for t in shared} == {HELSINKI, PORTO}


def test_a_note_already_stored_is_extracted_for_this_city_without_a_fetch(client, db, lookup,
                                                                         stubbed, calls):
    db.add(RedNotePost(note_id=BOTH_NOTE, title="美食", xsec_token="tok",
                       description=NOTES[BOTH_NOTE][0], image_urls=[]))
    db.commit()

    client.post("/initiate-plan", json=two_cities(lookup))
    run_worker()

    db.expire_all()
    assert BOTH_NOTE not in calls.fetch_note, "the body was already stored"
    assert not [t for t in tasks(db, TaskKind.REDNOTE_FETCH) if t.payload["note_id"] == BOTH_NOTE]
    for kind in (TaskKind.REDNOTE_EXTRACT, TaskKind.PLACES_RESOLVE):
        cities = {t.payload["city_id"] for t in tasks(db, kind)
                  if BOTH_NOTE in (t.payload.get("note_id"), t.payload.get("source_ref"))}
        assert cities == {HELSINKI, PORTO}, kind


def test_one_city_failing_still_leaves_the_trip_its_draft(client, db, lookup, stubbed, monkeypatch):
    break_cities(monkeypatch, ["Porto"])
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    assert {c: r.status for c, r in city_runs(db).items()} \
        == {HELSINKI: RunStatus.DONE, PORTO: RunStatus.FAILED}
    assert len(drafts(db, trip_id)) == 1
    assert claimed(db, trip_id) == {"pid-kauppahalli"}
    got = client.get(f"/trips/{trip_id}").json()
    assert got["ingest"]["status"] == RunStatus.DONE
    assert {f["kind"] for f in got["failures"]} == {TaskKind.YOUTUBE_SEARCH,
                                                    TaskKind.REDNOTE_SEARCH}


def test_no_city_producing_anything_is_terminal_and_undrafted(client, db, lookup, stubbed,
                                                              monkeypatch):
    break_cities(monkeypatch, ["Helsinki", "Porto"])
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    assert {r.status for r in city_runs(db).values()} == {RunStatus.FAILED}
    assert drafts(db, trip_id) == [], "nothing was ingested, so there is nothing to arrange"
    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] == RunStatus.FAILED


def test_a_city_wanting_credentials_outranks_its_finished_sibling(client, db, lookup, stubbed,
                                                                  monkeypatch):
    break_cities(monkeypatch, ["Porto"], code=ErrorCode.CREDENTIALS)
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    assert city_runs(db)[PORTO].status == RunStatus.NEEDS_CREDENTIALS
    assert client.get(f"/trips/{trip_id}").json()["ingest"]["status"] \
        == RunStatus.NEEDS_CREDENTIALS
    assert len(drafts(db, trip_id)) == 1


def test_a_task_that_exhausts_its_attempts_does_not_take_its_city_down(client, db, lookup, stubbed,
                                                                      monkeypatch):
    break_cities(monkeypatch, ["Porto 美食"], code=ErrorCode.TRANSIENT)
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    db.execute(update(IngestTask)
               .where(IngestTask.kind == TaskKind.REDNOTE_SEARCH,
                      IngestTask.payload["city_id"].astext == PORTO)
               .values(max_attempts=1))
    db.commit()

    run_worker()

    db.expire_all()
    dead = [t for t in tasks(db) if t.status != TaskStatus.DONE]
    assert [(t.kind, t.attempts, t.error_code) for t in dead] \
        == [(TaskKind.REDNOTE_SEARCH, 1, ErrorCode.TRANSIENT)]
    assert dead[0].status == TaskStatus.FAILED
    assert (city_runs(db)[PORTO].status, city_runs(db)[PORTO].failed_task_count) \
        == (RunStatus.DONE, 1)
    assert len(drafts(db, trip_id)) == 1


def test_a_throttled_task_goes_back_to_the_queue_without_starving_the_other_city(
        client, db, lookup, stubbed, monkeypatch):
    taken = []

    class Once(Throttler):
        def take(self):
            taken.append(1)
            if len(taken) == 1:
                raise Throttled("rednote budget", timedelta(minutes=45))

        def record(self):
            pass

    monkeypatch.setattr("tp_ingestions.limits.rednote",
                        lambda: Once("rednote", min_gap=0.0, jitter=0.0, limits=[]))
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]

    run_worker()

    db.expire_all()
    waiting = [t for t in tasks(db) if t.status != TaskStatus.DONE]
    assert [(t.kind, t.status, t.attempts) for t in waiting] \
        == [(TaskKind.REDNOTE_SEARCH, TaskStatus.PENDING, 0)], "the attempt is refunded"
    assert waiting[0].run_after > datetime.now(UTC)
    assert city_runs(db)[HELSINKI].status == RunStatus.RUNNING
    assert city_runs(db)[PORTO].status == RunStatus.DONE, "Porto drained while Helsinki waited"
    assert drafts(db, trip_id) == []

    db.execute(update(IngestTask).values(run_after=datetime.now(UTC)))
    db.commit()
    run_worker("w2")

    db.expire_all()
    assert set(db.scalars(select(IngestTask.status))) == {TaskStatus.DONE}
    assert len(drafts(db, trip_id)) == 1


def test_a_place_filed_under_a_city_the_trip_does_not_cover_is_still_claimed(client, db, lookup,
                                                                            stubbed):
    make_city(db, city_id=LISBON, name="Lisbon")
    trip_id = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    db.add(Place(place_id="pid-bolhao", city_id=LISBON, name="Mercado do Bolhão",
                 lat=41.149, lon=-8.606, confidence="high"))
    db.commit()

    run_worker()

    db.expire_all()
    assert db.get(Place, "pid-bolhao").city_id == LISBON, "never refiled"
    assert "pid-bolhao" in claimed(db, trip_id)


def test_two_trips_share_one_run_per_city_and_each_gets_its_own_draft(client, db, lookup, stubbed):
    both = client.post("/initiate-plan", json=two_cities(lookup)).json()["trip_id"]
    solo = client.post("/initiate-plan", json=two_cities(lookup, [PORTO])).json()["trip_id"]
    assert len(db.scalars(select(IngestRun.run_id)).all()) == 2

    run_worker()

    db.expire_all()
    assert claimed(db, both) == {"pid-kauppahalli", "pid-bolhao"}
    assert claimed(db, solo) == {"pid-bolhao"}
    assert (len(drafts(db, both)), len(drafts(db, solo))) == (1, 1)
