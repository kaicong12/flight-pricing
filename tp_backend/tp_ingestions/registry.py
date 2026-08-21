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
    from tp_ingestions.places import resolve as _places_resolve  # noqa: F401
    from tp_ingestions.rednote import extract as _rednote_extract  # noqa: F401
    from tp_ingestions.rednote import fetch as _rednote_fetch  # noqa: F401
    from tp_ingestions.rednote import ocr as _rednote_ocr  # noqa: F401
    from tp_ingestions.rednote import search as _rednote_search  # noqa: F401
    from tp_ingestions.youtube import extract as _youtube_extract  # noqa: F401
    from tp_ingestions.youtube import search as _youtube_search  # noqa: F401
