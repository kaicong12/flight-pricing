"""How the backend logs: one format, picked by whether a person is reading it.

Text on a TTY, which is `make dev`. JSON everywhere else, which is a container being read by a log
collector — both LogQL's `| json` and CloudWatch Logs Insights get fields out of it for free, where
plain text needs a parser expression per query. See docs/observability.md.
"""

import json
import logging
import sys
from datetime import UTC, datetime

TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)-16s %(message)s"
TEXT_DATEFMT = "%H:%M:%S"


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with a fixed set of short keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def install(level: int = logging.INFO, json_logs: bool | None = None) -> None:
    """Point the root logger at stderr with one of the two formats.

    uvicorn configures its own loggers before it imports the app and leaves the root logger alone, so
    this sits alongside the access log rather than replacing it.
    """
    if json_logs is None:
        json_logs = not sys.stderr.isatty()
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if json_logs else logging.Formatter(TEXT_FORMAT, TEXT_DATEFMT)
    )
    # force=True: basicConfig is a no-op once anything has put a handler on the root logger.
    logging.basicConfig(level=level, handlers=[handler], force=True)
