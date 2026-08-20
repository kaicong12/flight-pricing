"""The whole pipeline against stubbed sources: every seeded task runs, nothing ends up blocked."""

import pytest
from conftest import HELSINKI, make_city
from sqlalchemy import select

from libs import gemini
from libs.db import City, Extraction, IngestRun, IngestTask, RedNotePost, YouTubeVideo
from libs.db.enums import RunKind, RunStatus, Source, TaskKind, TaskStatus
from libs.ingest import seed_search_tasks
from libs.prompts import YOUTUBE_TRANSCRIPT
from tp_ingestions.rednote import client as rednote_client
from tp_ingestions.rednote import fetch as rednote_fetch
from tp_ingestions.report import report
from tp_ingestions.worker import Worker
from tp_ingestions.youtube import client as youtube_client
from tp_ingestions.youtube import extract as youtube_extract

HIT = {"video_id": "vid0000001a", "title": "Helsinki travel guide", "channel": "ch",
       "published_at": "2025-01-01T00:00:00Z"}

META = {"duration_s": 900, "captions": "MANUAL", "view_count": 50000,
        "description": "Everything to do in Helsinki", "lang": "en"}

NOTE = "68f0aa1c000000000e0139c4"

CARD = {"note_id": NOTE, "title": "赫尔辛基美食", "desc": "Löyly 很好吃", "time": 1770919541000,
        "note_translation": {"desc_trans": "Löyly is delicious"},
        "tag_list": [{"id": "1", "name": "赫尔辛基", "type": "topic"}],
        "image_list": [{"info_list": [{"image_scene": "WB_PRV", "url": "https://cdn/a.jpg"}]}]}


def rednote_result():
    return {"is_useful": True, "content_type": "food guide", "is_promotional": False,
            "city": "Helsinki", "city_confidence": "high",
            "places": [{"name_as_written": "Löyly", "name_local": "Löyly",
                        "name_local_confidence": "high", "category": "eat",
                        "why_go": "the post rates it", "sentiment": "recommended"}]}


def youtube_result():
    return {"is_travel_content": True, "content_type": "travel guide", "city": "Helsinki",
            "city_confidence": "high",
            "places": [{"name": "Vanha Kauppahalli", "name_confidence": "high", "category": "eat",
                        "timestamp": "03:00", "why_go": "the old market hall",
                        "sentiment": "recommended"}]}


@pytest.fixture
def seeded(db):
    make_city(db)
    run = IngestRun(run_id="run-1", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                    status=RunStatus.PENDING)
    db.add(run)
    db.flush()
    seed_search_tasks(db, run, db.get(City, HELSINKI))
    db.commit()
    return run


def fake_generate(prompt, rendered, images=None):
    """One stub for every handler: they all reach the same libs.gemini module object."""
    return youtube_result() if prompt is YOUTUBE_TRANSCRIPT else rednote_result()


@pytest.fixture
def stubbed(monkeypatch):
    """Every external client replaced. The throttle is stubbed too, or fetches would defer."""
    monkeypatch.setattr(youtube_client, "search", lambda *a, **k: [HIT])
    monkeypatch.setattr(youtube_client, "hydrate", lambda ids: {HIT["video_id"]: META})
    monkeypatch.setattr(youtube_extract.tx, "fetch_transcript",
                        lambda vid: [(0.0, "welcome to Helsinki")])

    monkeypatch.setattr("tp_ingestions.rednote.throttle.await_budget", lambda: None)
    monkeypatch.setattr(rednote_fetch, "await_budget", lambda: None)
    monkeypatch.setattr("tp_ingestions.rednote.search.await_budget", lambda: None)
    monkeypatch.setattr(rednote_client, "search_notes", lambda kw: [
        {"note_id": NOTE, "xsec_token": "tok", "title": "赫尔辛基美食", "likes": 196,
         "author": "a"}])
    monkeypatch.setattr(rednote_client, "fetch_note", lambda n, t: CARD)
    monkeypatch.setattr(gemini, "generate", fake_generate)


def test_a_seeded_run_drains_to_done(db, seeded, stubbed):
    ran = Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    # 2 youtube.search (en has no local partner for FI beyond fi) + rednote.search + fan-out.
    assert ran >= 4
    statuses = set(db.scalars(select(IngestTask.status)).all())
    assert statuses == {TaskStatus.DONE}
    assert db.get(IngestRun, "run-1").status == RunStatus.DONE


def test_nothing_in_the_drain_is_blocked(db, seeded, stubbed):
    """A kind with no handler blocks, which is how a missing handler shows up."""
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    blocked = db.scalars(
        select(IngestTask.kind).where(IngestTask.status == TaskStatus.BLOCKED)).all()
    assert blocked == []


def test_the_drain_writes_both_sources_into_extractions(db, seeded, stubbed):
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    rows = {e.source: e for e in db.scalars(select(Extraction)).all()}
    assert set(rows) == {Source.YOUTUBE, Source.REDNOTE}
    assert rows[Source.YOUTUBE].result["places"][0]["name"] == "Vanha Kauppahalli"
    assert rows[Source.REDNOTE].result["places"][0]["name_as_written"] == "Löyly"
    assert db.get(RedNotePost, NOTE).description == "Löyly 很好吃"
    assert db.get(YouTubeVideo, HIT["video_id"]).transcript is not None


def test_the_report_shows_what_the_run_yielded(db, seeded, stubbed, capsys):
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    assert report("run-1") == 0

    out = capsys.readouterr().out
    assert "Vanha Kauppahalli" in out and "Löyly" in out
    assert "city=Helsinki" in out and "confidence=high" in out
    assert "youtube" in out and "rednote" in out


def test_the_report_of_an_unknown_run_is_an_error(db, capsys):
    assert report("nope") == 1
    assert "no such run" in capsys.readouterr().out


def test_the_report_names_failed_tasks_and_their_error(db, seeded, stubbed, monkeypatch, capsys):
    """A run that half-worked has to say what it could not read."""
    monkeypatch.setattr(rednote_client, "fetch_note", lambda n, t: None)
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    report("run-1")

    out = capsys.readouterr().out
    assert "rednote.fetch" in out and "permanent" in out
    assert "returned no body" in out


def test_no_places_are_resolved_by_the_drain(db, seeded, stubbed):
    """places.resolve is out of scope, so nothing may reach the places tables yet."""
    from libs.db import Place, PlaceMention

    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    assert db.scalars(select(Place)).all() == []
    assert db.scalars(select(PlaceMention)).all() == []
    kinds = set(db.scalars(select(IngestTask.kind)).all())
    assert TaskKind.PLACES_RESOLVE not in kinds


def test_the_drain_marks_the_city_freshly_ingested(db, seeded, stubbed):
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    assert db.get(City, HELSINKI).last_ingested_at is not None


def test_a_second_drain_re_extracts_nothing(db, seeded, stubbed, monkeypatch):
    """Rerunning the search must reuse the cached bodies rather than pay Gemini again."""
    Worker(name="w1", poll_interval=0, reap_interval=1e9).drain()
    before = len(db.scalars(select(Extraction)).all())

    run = IngestRun(run_id="run-2", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                    status=RunStatus.PENDING)
    db.add(run)
    db.flush()
    seed_search_tasks(db, run, db.get(City, HELSINKI))
    db.commit()

    def never(*a, **k):
        raise AssertionError("gemini was called a second time for the same source")

    monkeypatch.setattr(gemini, "generate", never)
    Worker(name="w2", poll_interval=0, reap_interval=1e9).drain()

    db.expire_all()
    assert len(db.scalars(select(Extraction)).all()) == before
    assert db.get(IngestRun, "run-2").status == RunStatus.DONE
