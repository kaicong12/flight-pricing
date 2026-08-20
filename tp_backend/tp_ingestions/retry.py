"""The retry policy ErrorCode selects. Returning None means the task is terminal."""

import random
from datetime import timedelta

from libs.db.enums import ErrorCode

MAX_BACKOFF = timedelta(minutes=5)


def retry_after(code: ErrorCode, attempts: int) -> timedelta | None:
    """How long to wait before attempt number `attempts` + 1, or None to give up now."""
    if code in (ErrorCode.PERMANENT, ErrorCode.CREDENTIALS):
        # Neither is fixed by waiting: one is a bad request, the other needs a human to rotate a key.
        return None
    if code == ErrorCode.QUOTA:
        # Daily buckets (YouTube search.list) only reset on a clock, so back off in hours.
        return timedelta(hours=6)
    if code == ErrorCode.RATE_LIMITED:
        return timedelta(minutes=5 * attempts)
    seconds = min(MAX_BACKOFF.total_seconds(), 5 * 2 ** max(0, attempts - 1))
    return timedelta(seconds=seconds + random.uniform(0, seconds / 4))
