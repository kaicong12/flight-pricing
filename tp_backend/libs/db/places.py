"""Place writes shared by the worker and the API, so one ON CONFLICT clause serves both."""

from collections.abc import Sequence

from sqlalchemy import literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db.models import City, Place, Trip, TripPlace
from libs.places import VenueHit


def upsert_place(session: Session, city: City, hit: VenueHit, query: str,
                 confidence: str, reason: str, category: str | None = None) -> None:
    """Ratings move, so refresh them; never overwrite the name a better resolution already set."""
    updates = {"rating": hit.rating, "rating_count": hit.rating_count, "address": hit.address}
    if category is not None:
        updates["category"] = category
    session.execute(
        pg_insert(Place)
        .values(place_id=hit.place_id, city_id=city.city_id, name=hit.name, address=hit.address,
                lat=hit.lat, lon=hit.lon, rating=hit.rating, rating_count=hit.rating_count,
                primary_type=hit.primary_type, resolved_from_name=query, category=category,
                confidence=confidence, confidence_reason=reason)
        .on_conflict_do_update(index_elements=["place_id"], set_=updates)
    )


def claim_city_places(session: Session, trip_id: str, city_id: str) -> None:
    """Every place already known for a city, onto one trip. A claim is what shortlists a place."""
    session.execute(
        pg_insert(TripPlace)
        .from_select(["trip_id", "place_id"],
                     select(literal(trip_id), Place.place_id).where(Place.city_id == city_id))
        .on_conflict_do_nothing(index_elements=["trip_id", "place_id"])
    )


def claim_for_city_trips(session: Session, city_id: str, place_ids: Sequence[str]) -> None:
    """The other direction: places a run just resolved, onto every live trip in that city."""
    trips = session.scalars(
        select(Trip.trip_id).where(Trip.city_id == city_id, Trip.deleted.is_(False))
    ).all()
    if not trips or not place_ids:
        return
    session.execute(
        pg_insert(TripPlace)
        .values([{"trip_id": t, "place_id": p} for t in trips for p in place_ids])
        .on_conflict_do_nothing(index_elements=["trip_id", "place_id"])
    )
