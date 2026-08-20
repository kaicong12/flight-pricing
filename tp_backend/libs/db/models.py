"""SQLAlchemy tables — the source of truth Alembic autogenerates from.

Statuses are stored as plain text with CHECK constraints rather than Postgres enums, because adding
a value to a native enum needs its own migration.
"""

from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from libs.db.enums import (
    Confidence,
    ErrorCode,
    ExtractedFrom,
    RunKind,
    RunStatus,
    Sentiment,
    Source,
    TaskKind,
    TaskStatus,
)


class Base(DeclarativeBase):
    pass


def _in(column: str, enum) -> CheckConstraint:
    """CHECK constraint restricting a text column to an enum's values."""
    allowed = ", ".join(f"'{m.value}'" for m in enum)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"ck_{column}_{enum.__name__.lower()}")


def _ts(**kw) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), **kw)


class City(Base):
    """A city we ingest for, keyed by its Google place_id. lat/lon anchors the geofence."""

    __tablename__ = "cities"

    city_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    timezone: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    last_ingested_at: Mapped[datetime | None] = _ts()
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())

    places: Mapped[list["Place"]] = relationship(back_populates="city")
    trips: Mapped[list["Trip"]] = relationship(back_populates="city")


class Trip(Base):
    """One person's plan for a city. Dates and times are local wall clock; the zone is city.timezone.

    Storing an instant instead would drift, because a trip months out can cross a DST boundary.
    """

    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("depart_date >= arrive_date", name="ck_trip_dates"),
        Index("ix_trips_city", "city_id"),
    )

    trip_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    city_id: Mapped[str] = mapped_column(ForeignKey("cities.city_id"), nullable=False)
    arrive_date: Mapped[date] = mapped_column(Date, nullable=False)
    arrive_time: Mapped[time | None] = mapped_column(Time)
    depart_date: Mapped[date] = mapped_column(Date, nullable=False)
    depart_time: Mapped[time | None] = mapped_column(Time)
    extra_details: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(),
                                       onupdate=func.now())

    city: Mapped[City] = relationship(back_populates="trips")


class Place(Base):
    """A venue, identified by Google's opaque place_id — never by name."""

    __tablename__ = "places"
    __table_args__ = (
        _in("confidence", Confidence),
        Index("ix_places_city", "city_id"),
    )

    place_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    city_id: Mapped[str] = mapped_column(ForeignKey("cities.city_id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int | None] = mapped_column(Integer)
    primary_type: Mapped[str | None] = mapped_column(String(120))
    resolved_from_name: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now(),
                                       onupdate=func.now())

    city: Mapped[City] = relationship(back_populates="places")
    mentions: Mapped[list["PlaceMention"]] = relationship(back_populates="place")


class PlaceMention(Base):
    """One piece of evidence that a source recommended a place. Ranking counts these."""

    __tablename__ = "place_mentions"
    __table_args__ = (
        UniqueConstraint("place_id", "source", "source_ref", name="uq_mention_place_source_ref"),
        _in("source", Source),
        _in("sentiment", Sentiment),
        _in("extracted_from", ExtractedFrom),
        Index("ix_mentions_place", "place_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.place_id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    name_as_written: Mapped[str | None] = mapped_column(Text)
    why_go: Mapped[str | None] = mapped_column(Text)
    dish: Mapped[str | None] = mapped_column(Text)
    quoted_price: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(String(20), nullable=False)
    source_timestamp: Mapped[str | None] = mapped_column(String(16))
    extracted_from: Mapped[str] = mapped_column(String(8), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())

    place: Mapped[Place] = relationship(back_populates="mentions")


class RedNotePost(Base):
    """A fetched RedNote post. Cached so a note is never requested twice."""

    __tablename__ = "rednote_posts"

    note_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    xsec_token: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    image_urls: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    likes: Mapped[int | None] = mapped_column(Integer)
    author: Mapped[str | None] = mapped_column(Text)
    ip_location: Mapped[str | None] = mapped_column(String(64))
    posted_at: Mapped[datetime | None] = _ts()
    fetched_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class YouTubeVideo(Base):
    """A candidate travel video. captions=MANUAL is materially better than auto."""

    __tablename__ = "youtube_videos"

    video_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = _ts()
    duration_s: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)
    captions: Mapped[str | None] = mapped_column(String(16))
    lang: Mapped[str | None] = mapped_column(String(16))
    transcript: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class Extraction(Base):
    """Records that an LLM has read a source, including when it found nothing.

    Keyed by prompt_version and model so improving the prompt re-extracts instead of reusing a
    worse result, and so zero-yield sources are never paid for twice.
    """

    __tablename__ = "extractions"
    __table_args__ = (
        UniqueConstraint("source", "source_ref", "prompt_version", "model",
                         name="uq_extraction_ref_version"),
        _in("source", Source),
        _in("extracted_from", ExtractedFrom),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    extracted_from: Mapped[str | None] = mapped_column(String(8))
    is_useful: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_promotional: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                 server_default=text("false"))
    content_type: Mapped[str | None] = mapped_column(Text)
    place_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())


class IngestRun(Base):
    """What a waiting client polls. One per city ingestion, created with its seed tasks."""

    __tablename__ = "ingest_runs"
    __table_args__ = (
        _in("kind", RunKind),
        _in("status", RunStatus),
        # Two friends planning the same city join one run instead of double-spending the budget.
        Index("uq_run_active_city", "city_id", unique=True,
              postgresql_where=text("kind = 'city_ingest' AND status IN ('pending', 'running')")),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    city_id: Mapped[str | None] = mapped_column(ForeignKey("cities.city_id"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False,
                                       server_default=text("'pending'"))
    requested_by: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = _ts()
    failed_task_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)

    tasks: Mapped[list["IngestTask"]] = relationship(back_populates="run",
                                                     cascade="all, delete-orphan")


class IngestTask(Base):
    """The queue and the progress ledger in one table.

    Claimed with FOR UPDATE SKIP LOCKED; locked_at is a lease, so a task whose worker died is
    reclaimed rather than stuck.
    """

    __tablename__ = "ingest_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "dedupe_key", name="uq_task_run_dedupe"),
        _in("kind", TaskKind),
        _in("status", TaskStatus),
        _in("source", Source),
        _in("error_code", ErrorCode),
        Index("ix_task_claim", "status", "run_after", "task_id"),
        Index("ix_task_run_kind", "run_id", "kind", "status"),
        Index("ix_task_lease", "status", "locked_at"),
    )

    task_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("ingest_runs.run_id", ondelete="CASCADE"),
                                        nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str | None] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Wide because keys embed a city_id, which is a Google place_id.
    dedupe_key: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False,
                                        server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))
    run_after: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    locked_by: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = _ts()
    error_code: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts(nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = _ts()

    run: Mapped[IngestRun] = relationship(back_populates="tasks")
