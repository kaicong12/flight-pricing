"""Test DB fixtures. Runs the real migrations against a throwaway database."""

import importlib
import os
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from libs.db import City, Place, PlaceMention, RedNotePost, YouTubeVideo
from libs.db.enums import Confidence, ExtractedFrom, Sentiment, Source
from libs.places import CityDetails
from libs.routing import Leg, RouteResult
from libs.settings import settings
from tp_api.deps import city_lookup, db_session, hours_lookup, route_compute
from tp_api.main import app
from tp_api.schemas import today_utc
from tp_ingestions.throttle import Throttler

TABLES = ["itinerary_items", "trip_dismissals", "place_hours", "place_mentions", "places",
          "place_queries", "ingest_tasks", "ingest_runs", "extractions", "rednote_posts",
          "youtube_videos", "throttle_calls", "trips", "cities"]

HELSINKI = "ChIJkQYhlscLkkYRY_fiO4S9Ts0"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly rather than spend real quota: a stub that misses is otherwise a silent live call.

    Only the real transports are blocked. TestClient rides ASGITransport, and psycopg does not go
    through either of these, so both keep working.
    """
    def blocked(self, *a, **kw):
        raise AssertionError(f"live network call in a test via {type(self).__name__} — stub it")

    monkeypatch.setattr("httpx.HTTPTransport.handle_request", blocked)
    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", blocked)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """No test sleeps on a gap or writes throttle history.

    tests/test_throttle.py builds Throttlers directly, so it is unaffected by this.
    """
    free = Throttler("test", min_gap=0.0, jitter=0.0, limits=[])
    monkeypatch.setattr(free, "take", lambda: None)
    monkeypatch.setattr(free, "record", lambda: None)
    monkeypatch.setattr("tp_ingestions.limits.rednote", lambda: free)
    monkeypatch.setattr("tp_ingestions.limits.gemini", lambda: free)


def make_city(db, city_id=HELSINKI, name="Helsinki", **kw):
    """A city row keyed the way the app keys them — by Google place_id."""
    db.add(City(city_id=city_id, name=name, country="FI", timezone="Europe/Helsinki",
                lat=60.17, lon=24.94, **kw))
    db.commit()
    return city_id


HELSINKI_DETAILS = CityDetails(place_id=HELSINKI, name="Helsinki", country="FI",
                               timezone="Europe/Helsinki", lat=60.17, lon=24.94)


def plan_body(**kw):
    """A valid /initiate-plan payload, dated relative to today so it never goes stale."""
    arrive = today_utc() + timedelta(days=30)
    return {"city_place_id": HELSINKI,
            "arrive_date": arrive.isoformat(),
            "arrive_time": "14:30",
            "depart_date": (arrive + timedelta(days=3)).isoformat(),
            "depart_time": "18:05",
            "extra_details": "food and design, one proper sauna"} | kw


def make_place(db, city_id=HELSINKI, place_id="p1", name="A Place", **kw):
    """A resolved place. lat/lon and rating_count are always populated in real data."""
    db.add(Place(place_id=place_id, city_id=city_id, name=name,
                 lat=kw.pop("lat", 60.17), lon=kw.pop("lon", 24.94),
                 rating=kw.pop("rating", 4.5), rating_count=kw.pop("rating_count", 100),
                 confidence=kw.pop("confidence", Confidence.HIGH), **kw))
    db.commit()
    return place_id


def make_mention(db, place_id, *, source=Source.YOUTUBE, source_ref="ref1", category="see",
                 why_go=None, sentiment=Sentiment.RECOMMENDED):
    """One piece of evidence. The count of these is the shortlist's ranking signal."""
    db.add(PlaceMention(place_id=place_id, source=source, source_ref=source_ref,
                        category=category, why_go=why_go, sentiment=sentiment,
                        extracted_from=ExtractedFrom.TEXT, prompt_version="v1", model="test"))
    db.commit()


def make_video(db, video_id="ref1", title="Tromsø in 3 Days"):
    """The row a youtube mention's source_ref joins to for its title."""
    db.add(YouTubeVideo(video_id=video_id, title=title))
    db.commit()
    return video_id


def make_note(db, note_id="note1", title="特罗姆瑟美食", xsec_token="tok", **kw):
    """The row a rednote mention's source_ref joins to. xsec_token is what makes the link openable."""
    db.add(RedNotePost(note_id=note_id, title=title, xsec_token=xsec_token, **kw))
    db.commit()
    return note_id


@pytest.fixture
def lookup():
    """Stands in for Google Places. Reassign ["fn"] to make a test's lookup fail."""
    return {"fn": lambda place_id: HELSINKI_DETAILS}


@pytest.fixture
def hours():
    """Stands in for Place Details. Reassign ["fn"] to change what hours a test sees."""
    return {"fn": lambda place_ids: {}}


@pytest.fixture
def routes():
    """Stands in for Routes. Defaults to a 10-minute 800 m leg between each pair."""
    def default(place_ids, mode, depart_iso):
        legs = [Leg(seconds=600, meters=800, transit_steps=[]) for _ in place_ids[:-1]]
        return RouteResult(legs=legs, polyline="_p~iF~ps|U", total_seconds=600 * len(legs),
                           total_meters=800 * len(legs))
    return {"fn": default}


@pytest.fixture
def client(db, lookup, hours, routes):
    app.dependency_overrides[db_session] = lambda: db
    app.dependency_overrides[city_lookup] = lambda: (lambda pid: lookup["fn"](pid))
    app.dependency_overrides[hours_lookup] = lambda: (lambda pids: hours["fn"](pids))
    app.dependency_overrides[route_compute] = lambda: (
        lambda pids, mode, iso: routes["fn"](pids, mode, iso))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _test_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", settings().database_url + "_test")


@pytest.fixture(scope="session")
def engine():
    url = _test_url()
    admin = create_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    name = url.rsplit("/", 1)[1]
    with admin.connect() as c:
        if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": name}).first():
            c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    cfg = Config(str(Path(__file__).resolve().parents[1] / "libs/db/alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    eng = create_engine(url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _redirect_module_sessions(engine, monkeypatch):
    """The worker opens its own sessions via libs.db.session, which is bound to the real engine at
    import time. Without this, worker tests would write to the development database."""
    # Fetched from importlib, not `import libs.db.session`: libs.db re-exports the `session`
    # function, which shadows the submodule of the same name.
    module = importlib.import_module("libs.db.session")
    monkeypatch.setattr(module, "SessionLocal",
                        sessionmaker(bind=engine, expire_on_commit=False, future=True))


@pytest.fixture
def db(engine):
    """A session against a truncated database."""
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    s = factory()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
