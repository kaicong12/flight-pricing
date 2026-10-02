"""The retry policy ErrorCode selects. Returning None means the task is terminal."""

import random
from datetime import timedelta

from libs.db.enums import ErrorCode

MAX_BACKOFF = timedelta(minutes=5)


def retry_after(code: ErrorCode, attempts: int) -> timedelta | None:
    """How long to wait before attempt number `attempts` + 1, or None to give up now."""
    if code in (ErrorCode.PERMANENT, ErrorCode.CREDENTIALS):
        return None
    if code == ErrorCode.QUOTA:
        # YouTube's daily quota only resets on a clock.
        return timedelta(hours=6)
    if code == ErrorCode.RATE_LIMITED:
        return timedelta(minutes=5 * attempts)
    seconds = min(MAX_BACKOFF.total_seconds(), 5 * 2 ** max(0, attempts - 1))
    return timedelta(seconds=seconds + random.uniform(0, seconds / 4))
