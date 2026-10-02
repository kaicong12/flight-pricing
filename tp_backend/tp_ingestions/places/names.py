"""Turning an extracted name into a cache key, a decision to call Google, and a confidence score.

Pure functions, so they can be tuned against real extractions with no API calls.
"""

import re
import unicodedata

from libs.db.enums import Confidence
from libs.places import VenueHit

# NFKD does not decompose these letters.
FOLD = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "Å": "a",
                      "ß": "ss", "đ": "d", "ł": "l", "ð": "d", "þ": "th", "ı": "i"})

# Places answers a bare category with its best-known venue.
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

CHAINS = {
    "mcdonalds", "burger king", "kfc", "subway", "starbucks", "dominos", "pizza hut",
    "hard rock cafe", "7 eleven", "seven eleven", "circle k", "espresso house", "waynes coffee",
    "rema 1000", "eurospar", "spar", "kiwi", "coop", "meny", "bunnpris", "joker", "extra",
    "narvesen", "vinmonopolet", "vitusapotek", "apotek 1", "boots apotek", "egon", "peppes pizza",
    "dominos pizza", "olivia", "bit", "deli de luca", "jafs", "max", "tgi fridays",
    "scandic", "thon hotel", "radisson", "clarion", "comfort hotel", "quality hotel", "ibis",
}

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



def _has_latin(s: str) -> bool:
    return bool(re.search(r"[a-z]", query_norm(s)))


def _is_cjk(s: str) -> bool:
    return bool(re.search(r"[　-鿿]", s or ""))


def judge(query: str, hit: VenueHit) -> tuple[Confidence | None, str]:
    """Confidence in the resolution, or None to reject it.

    Type is not a signal: Fjellheisen, Tromsø's top attraction, comes back with an empty
    primaryTypeDisplayName and only point_of_interest, so a type rule would reject it.
    """
    if _is_chain(query_norm(hit.name)):
        return None, f"chain ({hit.name})"

    if _is_cjk(query) and not _has_latin(query) and not _is_cjk(hit.name):
        return Confidence.MEDIUM, f"unconfirmed identity: {query!r} resolved to a Latin name"

    if not (tokens(query) & tokens(hit.name)):
        return Confidence.MEDIUM, "name shares no token with the query"
    return Confidence.HIGH, "name matches the query"
