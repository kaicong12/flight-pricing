"""Place writes shared by the worker and the API, so one ON CONFLICT clause serves both."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from libs.db.models import City, Place
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
