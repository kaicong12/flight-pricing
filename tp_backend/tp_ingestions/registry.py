"""TaskKind to handler. A kind with no handler is blocked, not failed, so a run still settles."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from libs.db.enums import TaskKind
from tp_ingestions.queue import ClaimedTask

Handler = Callable[[Session, ClaimedTask], dict]

HANDLERS: dict[str, Handler] = {}


def handles(kind: TaskKind):
    def register(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return register


def load_handlers() -> None:
    """Import the modules whose decorators populate HANDLERS."""
    from tp_ingestions.rednote import search as _rednote_search  # noqa: F401
    from tp_ingestions.youtube import search as _youtube_search  # noqa: F401
