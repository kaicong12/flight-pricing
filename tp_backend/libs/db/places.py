"""Place writes shared by the worker and the API, so one ON CONFLICT clause serves both, plus the
trip-to-city predicate those writes are aimed by."""

from collections.abc import Sequence

from sqlalchemy import literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db.models import City, Place, PlaceQuery, Trip, TripCity, TripPlace
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
    resolved = select(PlaceQuery.place_id).where(PlaceQuery.city_id == city_id)
    session.execute(
        pg_insert(TripPlace)
        .from_select(["trip_id", "place_id"],
                     select(literal(trip_id), Place.place_id)
                     .where(or_(Place.city_id == city_id, Place.place_id.in_(resolved))))
        .on_conflict_do_nothing(index_elements=["trip_id", "place_id"])
    )


def covers_city(city_id: str):
    return (select(TripCity.city_id)
            .where(TripCity.trip_id == Trip.trip_id, TripCity.city_id == city_id)
            .exists())


def cities_by_trip(session: Session, trip_ids: Sequence[str]) -> dict[str, list[str]]:
    if not trip_ids:
        return {}
    out: dict[str, list[str]] = {}
    for trip_id, city_id in session.execute(
        select(TripCity.trip_id, TripCity.city_id)
        .join(Trip, Trip.trip_id == TripCity.trip_id)
        .where(TripCity.trip_id.in_(trip_ids))
        # created_at ties: now() is the transaction clock and a trip writes every row in one.
        .order_by(TripCity.city_id != Trip.city_id, TripCity.created_at, TripCity.city_id)
    ):
        out.setdefault(trip_id, []).append(city_id)
    return out


def trip_cities(session: Session, trip: Trip) -> list[City]:
    ids = cities_by_trip(session, [trip.trip_id]).get(trip.trip_id) or [trip.city_id]
    found = {c.city_id: c for c in session.scalars(select(City).where(City.city_id.in_(ids)))}
    return [found[i] for i in ids if i in found]


def claim_for_city_trips(session: Session, city_id: str, place_ids: Sequence[str]) -> None:
    trips = session.scalars(
        select(Trip.trip_id).where(covers_city(city_id), Trip.deleted.is_(False))
    ).all()
    if not trips or not place_ids:
        return
    session.execute(
        pg_insert(TripPlace)
        .values([{"trip_id": t, "place_id": p} for t in trips for p in place_ids])
        .on_conflict_do_nothing(index_elements=["trip_id", "place_id"])
    )
