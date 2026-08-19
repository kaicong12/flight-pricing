"""Status and kind vocabularies shared by the models and the worker."""

from enum import StrEnum


class Source(StrEnum):
    YOUTUBE = "youtube"
    REDNOTE = "rednote"
    PLACES = "places"
    GEMINI = "gemini"


class RunKind(StrEnum):
    CITY_INGEST = "city_ingest"
    TRIP_PLANNING = "trip_planning"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    NEEDS_CREDENTIALS = "needs_credentials"


class TaskKind(StrEnum):
    YOUTUBE_SEARCH = "youtube.search"
    YOUTUBE_EXTRACT = "youtube.extract"
    REDNOTE_SEARCH = "rednote.search"
    REDNOTE_FETCH = "rednote.fetch"
    REDNOTE_EXTRACT = "rednote.extract"
    REDNOTE_OCR = "rednote.ocr"
    PLACES_RESOLVE = "places.resolve"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class ErrorCode(StrEnum):
    """Decides the retry policy; see worker.retry_after."""

    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    CREDENTIALS = "credentials"
    QUOTA = "quota"
    PERMANENT = "permanent"


class Sentiment(StrEnum):
    RECOMMENDED = "recommended"
    MIXED = "mixed"
    NOT_RECOMMENDED = "not_recommended"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExtractedFrom(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class CredentialState(StrEnum):
    OK = "ok"
    EXPIRED = "expired"
    MISSING = "missing"
