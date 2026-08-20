"""Request-scoped dependencies. Both are overridden in tests so no live API is called."""

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from libs.db import session
from libs.places import CityDetails, city_details

CityLookup = Callable[[str], CityDetails]


def db_session() -> Iterator[Session]:
    with session() as s:
        yield s


def city_lookup() -> CityLookup:
    return city_details
