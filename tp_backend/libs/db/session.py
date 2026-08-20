"""Engine and session factory."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from libs.settings import settings

engine = create_engine(
    settings().database_url,
    pool_size=settings().db_pool_size,
    max_overflow=settings().db_max_overflow,
    pool_pre_ping=True,
    # Managed Postgres drops idle connections; recycling avoids paying for a pre-ping to find out.
    pool_recycle=1800,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session() -> Iterator[Session]:
    """A session wrapped in one transaction — commits on success, rolls back on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
