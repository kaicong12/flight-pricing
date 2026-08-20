"""How a handler tells the worker what went wrong, and therefore whether to retry."""

from datetime import timedelta

from libs.db.enums import ErrorCode


class Throttled(Exception):
    """A local budget said not yet, so the task did no work at all.

    Distinct from a RATE_LIMITED TaskError, which is the remote source pushing back. Waiting for our
    own budget must not spend an attempt, or a queue of throttled tasks fails on max_attempts while
    nothing is actually wrong.
    """

    def __init__(self, message: str, retry_after: timedelta):
        super().__init__(message)
        self.retry_after = retry_after


class TaskError(Exception):
    """A handler failure classified for the retry policy.

    retry_after overrides the policy when the source told us how long to wait.
    """

    def __init__(self, code: ErrorCode, message: str, retry_after: timedelta | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
