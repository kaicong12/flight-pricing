"""Request-scoped dependencies. All are overridden in tests so no live API is called."""

from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from libs.db import session
from libs.places import CityDetails, CitySuggestion, city_details, search_cities

CityLookup = Callable[[str], CityDetails]
CitySearch = Callable[[str, int], list[CitySuggestion]]


def db_session() -> Iterator[Session]:
    with session() as s:
        yield s


def city_lookup() -> CityLookup:
    return city_details


def city_search() -> CitySearch:
    return search_cities
