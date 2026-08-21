"""The worker's call budgets. Built lazily so a settings change is picked up without an import cycle.

Only RedNote and Gemini are paced. YouTube's search.list is one call per language per city, and
Places is called once per unresolved name behind a cache, so both stay reactive to a 429.
"""

from functools import lru_cache

from libs.settings import settings
from tp_ingestions.throttle import Throttler


@lru_cache
def rednote() -> Throttler:
    s = settings()
    return Throttler("rednote", min_gap=s.rednote_min_gap_s, jitter=s.rednote_jitter_s,
                     limits=[(s.rednote_max_per_hour, 3600), (s.rednote_max_per_day, 86400)])


@lru_cache
def gemini() -> Throttler:
    s = settings()
    # A wider inline wait than RedNote's: extraction runs as a child call inside rednote.fetch, so
    # deferring it would roll back the note body and re-spend a RedNote call on the retry.
    return Throttler("gemini", min_gap=s.gemini_min_gap_s, jitter=1.0, max_inline_wait=60.0,
                     limits=[(s.gemini_max_per_minute, 60), (s.gemini_max_per_day, 86400)])
