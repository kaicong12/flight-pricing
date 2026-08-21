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

from libs.db import City
from libs.places import CityDetails
from libs.settings import settings
from tp_api.deps import city_lookup, db_session
from tp_api.main import app
from tp_api.schemas import today_utc
from tp_ingestions.throttle import Throttler

TABLES = ["place_mentions", "places", "place_queries", "ingest_tasks", "ingest_runs", "extractions",
          "rednote_posts", "youtube_videos", "throttle_calls", "trips", "cities"]

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


@pytest.fixture
def lookup():
    """Stands in for Google Places. Reassign ["fn"] to make a test's lookup fail."""
    return {"fn": lambda place_id: HELSINKI_DETAILS}


@pytest.fixture
def client(db, lookup):
    app.dependency_overrides[db_session] = lambda: db
    app.dependency_overrides[city_lookup] = lambda: (lambda pid: lookup["fn"](pid))
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
