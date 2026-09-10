"""Run an ingestion worker: python -m tp_ingestions [--once] [--name w1]"""

import argparse
import logging
import sys

from libs import logs
from tp_ingestions.worker import Worker


def main() -> int:
    ap = argparse.ArgumentParser(prog="tp_ingestions")
    ap.add_argument("--once", action="store_true",
                    help="drain everything currently due, then exit")
    ap.add_argument("--name", help="worker id recorded in locked_by; defaults to host:pid")
    ap.add_argument("--poll-interval", type=float, default=2.0)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    # Same format as the API's, which matters once both are in one log store: the worker's own
    # basicConfig kept it readable on a TTY but left `{service="worker"} | json` matching nothing.
    logs.install(level=logging.WARNING if args.quiet else logging.INFO)

    worker = Worker(name=args.name, poll_interval=args.poll_interval)
    worker.install_signal_handlers()
    if args.once:
        worker.drain()
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
