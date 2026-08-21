"""Turning an extracted name into a cache key, a decision to call Google, and a confidence score.

Pure functions, so they can be tuned against real extractions with no API calls — see
`python -m tp_ingestions --resolve-preview <run_id>`.
"""

import math
import re
import unicodedata

from libs.db.enums import Confidence
from libs.places import VenueHit

# NFKD leaves these alone: they are letters, not accented forms. Without folding them,
# "Tromsø Cathedral" and "Tromso Cathedral" are different cache keys.
FOLD = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "Å": "a",
                      "ß": "ss", "đ": "d", "ł": "l", "ð": "d", "þ": "th", "ı": "i"})

# A name made only of these is a category, not a venue. Places answers a bare "bakery" with the
# best-known bakery in the box — 4.7 stars, 553 ratings — and nothing in the response says it was a
# category. So this list is the only defence, and it has to run before the call.
GENERIC = {
    "the", "a", "an", "and", "of", "or", "in", "at", "some", "this", "that", "my", "our",
    "cafe", "coffee", "restaurant", "bar", "pub", "bistro", "bakery", "brewery", "diner", "eatery",
    "museum", "gallery", "church", "cathedral", "chapel", "temple", "shrine", "mosque",
    "market", "hall", "park", "square", "garden", "beach", "island", "mountain", "lake", "river",
    "hotel", "hostel", "sauna", "spa", "shop", "store", "supermarket", "mall", "pharmacy",
    "library", "stadium", "arena", "theatre", "theater", "cinema", "aquarium", "zoo",
    "airport", "station", "harbor", "harbour", "port", "terminal", "bus", "train", "ferry",
    "cable", "car", "lift", "tram", "centre", "center", "visitor", "tourist", "information",
    "street", "road", "avenue", "downtown", "old", "new", "town", "city", "food", "drink",
    "place", "spot", "area", "house", "culture", "art", "arts", "local", "traditional", "burger",
    "pizza", "sushi", "ramen", "seafood", "fish", "meat", "cake", "dessert", "ice", "sweetheart",
}

# Present in many cities, so a recommendation of one is not a recommendation of a place. Matched on
# the normalised name, whole-string or as a leading word, so "Bardus Bistro" is unaffected.
CHAINS = {
    "mcdonalds", "burger king", "kfc", "subway", "starbucks", "dominos", "pizza hut",
    "hard rock cafe", "7 eleven", "seven eleven", "circle k", "espresso house", "waynes coffee",
    "rema 1000", "eurospar", "spar", "kiwi", "coop", "meny", "bunnpris", "joker", "extra",
    "narvesen", "vinmonopolet", "vitusapotek", "apotek 1", "boots apotek", "egon", "peppes pizza",
    "dominos pizza", "olivia", "bit", "deli de luca", "jafs", "max", "tgi fridays",
    "scandic", "thon hotel", "radisson", "clarion", "comfort hotel", "quality hotel", "ibis",
}

_KM_PER_DEG_LAT = 111.0


def query_norm(name: str) -> str:
    """The cache key. Folded and stripped, but CJK is kept — it is often the only name we have."""
    s = (name or "").strip().lower().translate(FOLD)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w　-鿿]+", " ", s, flags=re.UNICODE)
    return " ".join(s.split())[:200]


def tokens(name: str) -> set[str]:
    return {w for w in query_norm(name).split() if len(w) > 2 and w not in GENERIC}


def _squash(name: str) -> str:
    """Normalised with spaces removed, so "McDonald's" and "mcdonalds" compare equal."""
    return query_norm(name).replace(" ", "")


_CHAINS = {_squash(c) for c in CHAINS}
# Only distinctive brands may match as a prefix. "max" or "bit" as a prefix would reject a real
# venue whose name merely starts that way.
_CHAIN_PREFIXES = {c for c in _CHAINS if len(c) >= 6}


def _is_chain(key: str) -> bool:
    words = key.split()
    if _squash(key) in _CHAINS:
        return True
    return any("".join(words[:n]) in _CHAIN_PREFIXES for n in range(1, min(3, len(words)) + 1))


def reject_before_call(name: str) -> str | None:
    """Why this name must not be sent to Google, or None to go ahead."""
    key = query_norm(name)
    if not key:
        return "empty after normalisation"
    if _is_chain(key):
        return f"chain ({key})"
    if all(w in GENERIC or w.isdigit() for w in key.split()):
        return f"generic category, not a venue ({key})"
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular, which is accurate enough over a city and cheap."""
    mean = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * _KM_PER_DEG_LAT * math.cos(mean)
    dy = (lat2 - lat1) * _KM_PER_DEG_LAT
    return math.hypot(dx, dy)


def _has_latin(s: str) -> bool:
    return bool(re.search(r"[a-z]", query_norm(s)))


def _is_cjk(s: str) -> bool:
    return bool(re.search(r"[　-鿿]", s or ""))


def judge(query: str, hit: VenueHit) -> tuple[Confidence | None, str]:
    """Confidence in the resolution, or None to reject it.

    Rating count is the signal. Type is not: Fjellheisen, Tromsø's top attraction, comes back with
    an empty primaryTypeDisplayName and only point_of_interest, so a type rule would reject it.
    """
    count = hit.rating_count or 0
    if count == 0:
        return None, "no ratings — not a destination"

    # The pre-call gate only sees what the source wrote, and "Storgata" is a street that resolves to
    # the supermarket on it. The official name is free to check and catches what the query missed.
    if _is_chain(query_norm(hit.name)):
        return None, f"chain ({hit.name})"

    # A Chinese name landing on a Latin one is only identity if a Latin fragment carried the match.
    if _is_cjk(query) and not _has_latin(query) and not _is_cjk(hit.name):
        return Confidence.MEDIUM, f"unconfirmed identity: {query!r} resolved to a Latin name"

    if count >= 100:
        return Confidence.HIGH, f"{count} ratings"
    if count < 20:
        return Confidence.LOW, f"only {count} ratings"
    if not (tokens(query) & tokens(hit.name)):
        return Confidence.MEDIUM, "name shares no token with the query"
    return Confidence.MEDIUM, f"{count} ratings"
