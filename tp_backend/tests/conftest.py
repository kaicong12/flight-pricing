"""Test DB fixtures. Runs the real migrations against a throwaway database."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from libs.settings import settings

TABLES = ["place_mentions", "places", "ingest_tasks", "ingest_runs", "extractions",
          "rednote_posts", "youtube_videos", "cities"]


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
