"""How a handler tells the worker what went wrong, and therefore whether to retry."""

from datetime import timedelta

from libs.db.enums import ErrorCode


class TaskError(Exception):
    """A handler failure classified for the retry policy.

    retry_after overrides the policy when the source told us how long to wait.
    """

    def __init__(self, code: ErrorCode, message: str, retry_after: timedelta | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
