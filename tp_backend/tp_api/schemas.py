"""Request and response bodies for the planning API."""

from datetime import UTC, date, datetime, time, timedelta

from pydantic import BaseModel, Field, model_validator

MAX_TRIP_DAYS = 14

def today_utc() -> date:
    """Trip dates are local to the city, so compare against UTC and allow a day of slack."""
    return datetime.now(UTC).date()


NAME_MAX = 120


class TripPatch(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX)


class InitiatePlanRequest(BaseModel):
    city_place_id: str = Field(min_length=1, max_length=255)
    name: str | None = Field(default=None, max_length=NAME_MAX)
    arrive_date: date
    arrive_time: time | None = None
    depart_date: date
    depart_time: time | None = None
    extra_details: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_span(self):
        if self.depart_date < self.arrive_date:
            raise ValueError("depart_date is before arrive_date")
        if (self.depart_date - self.arrive_date).days > MAX_TRIP_DAYS:
            raise ValueError(f"trip is longer than {MAX_TRIP_DAYS} days")
        if self.arrive_date < today_utc() - timedelta(days=1):
            raise ValueError("arrive_date is in the past")
        return self


class CitySuggestionOut(BaseModel):
    place_id: str
    description: str
    main_text: str | None = None


class CityOut(BaseModel):
    city_id: str
    name: str
    country: str | None = None
    timezone: str | None = None


class IngestOut(BaseModel):
    run_id: str
    status: str


class TaskProgress(BaseModel):
    kind: str
    status: str
    count: int


class TaskFailure(BaseModel):
    """Sources we could not read, grouped by why."""

    kind: str
    status: str
    error_code: str | None = None
    last_error: str | None = None
    count: int = 1


class TripOut(BaseModel):
    trip_id: str
    name: str | None = None
    city: CityOut
    arrive_date: date
    arrive_time: time | None = None
    depart_date: date
    depart_time: time | None = None
    extra_details: str | None = None
    ingest: IngestOut | None = None
    deleted: bool = False


class TripStatusOut(TripOut):
    # What the caller may do with this trip, so the UI can hide what would only 403.
    your_role: str
    progress: list[TaskProgress] = []
    failures: list[TaskFailure] = []
    # The route.plan task's status, or None if this trip was never drafted. The client polls on it.
    draft: str | None = None


class TripSummaryOut(BaseModel):
    trip_id: str
    name: str | None = None
    city: CityOut
    arrive_date: date
    depart_date: date
    ingest: IngestOut | None = None
    your_role: str
    tasks_done: int = 0
    tasks_total: int = 0
    place_count: int = 0


