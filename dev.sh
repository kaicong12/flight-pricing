#!/usr/bin/env bash
# Run the backend locally: migrations, then tp_api and the ingestion worker together.
# One Ctrl-C stops both. The client is a separate `npm run dev` in tp_client (or Vercel).
set -euo pipefail

cd "$(dirname "$0")/tp_backend"

PORT="${PORT:-8000}"
WORKER_ARGS="${WORKER_ARGS:-}"

# Kill the whole process group on exit, or uvicorn's reloader children outlive the script.
pids=""
cleanup() {
    trap - INT TERM EXIT
    for pid in $pids; do
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> migrating"
uv run alembic -c libs/db/alembic.ini upgrade head

echo "==> api on http://localhost:$PORT  (worker: python -m tp_ingestions $WORKER_ARGS)"
set -m
uv run uvicorn tp_api.main:app --port "$PORT" --reload &
pids="$pids $!"
# Not --once: a RedNote throttle wait goes back to the queue, and drain() exits when nothing is due.
uv run python -m tp_ingestions $WORKER_ARGS &
pids="$pids $!"
set +m

# Exit as soon as either dies, so a crashed worker is not hidden by a healthy api. Polled rather
# than `wait -n`, which macOS's bash 3.2 does not have.
while :; do
    for pid in $pids; do
        kill -0 "$pid" 2>/dev/null || exit 1
    done
    sleep 1
done
