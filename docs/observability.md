# Observability

One metric scraped from the API, and every container's logs pushed to Loki. `make observability`
brings up Prometheus, Loki, Alloy and Grafana; the backend stack in `docker-compose.yml` is untouched
and still fits a t4g.micro.

Measured at idle with a live scrape: prometheus 29 MiB, grafana 71 MiB. Small enough to fit the
deploy box, still kept off it — a dashboard hosted on the instance it watches goes down with it.

## Where the numbers live

The API stores nothing long-term. `tp_api/metrics.py` keeps counters in process memory and renders
them at `GET /metrics`; Prometheus reads that page every 15s and writes each reading to its own
on-disk TSDB. The history is Prometheus's, not the app's.

That makes the durability boundary the **`prometheus-data` volume**, not the API process. Restarting
the API is harmless. `docker compose ... down -v` is what destroys the history.

Counters reset to zero when the API restarts, and that is expected rather than a bug: `rate()` and
`increase()` are reset-aware, so a restart leaves a notch in the raw series and correct numbers in
every query below. Never graph a raw counter.

Retention is 90 days (`--storage.tsdb.retention.time`), about 200 MB at ~2 MB/day. Past a few months
the answer is `remote_write` to a long-term store, not a bigger disk.

## The metric

```
http_request_duration_seconds{method, route, status}
```

A histogram is three series families — `_bucket`, `_sum`, `_count` — so this one metric answers
everything on the dashboard. A separate `http_requests_total` counter would be redundant:

| | |
|---|---|
| requests/sec | `rate(http_request_duration_seconds_count[5m])` |
| average | `rate(..._sum[5m]) / rate(..._count[5m])` |
| p95 | `histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))` |
| error rate | `sum(rate(..._count{status=~"5.."}[5m])) / sum(rate(..._count[5m]))` |

**`route` is the matched route template, never the request path.** `/trips/{trip_id}`, not
`/trips/abc-123`. Label values multiply into separate series, so raw paths would mint one series per
trip and eventually take Prometheus down. `tests/test_metrics.py` locks this down, and a request that
matched no route is not recorded at all rather than recorded under an unbounded label.

Buckets are `prometheus_client`'s defaults (5ms → 10s), which happen to suit this API: `/trips` sits
in the bottom two and `/initiate-plan` blocks on a Places call and lives in the upper ones.

## Logs

Metrics are pulled; **logs are pushed**, and that one difference shapes everything here. Prometheus
reaches into the API on its own schedule, so a laptop can scrape a deployed box and a closed laptop
just leaves a gap in a graph. Loki cannot work that way: Alloy pushes the moment a line is written, so
Loki has to be up and reachable or the line is gone for good.

```
container stdout ──▶ docker json-file ──▶ alloy ──push──▶ loki ◀──query── grafana
```

**Nobody visits Loki.** It has no UI — it is an HTTP API on `:3100` that Alloy writes to and Grafana
reads from server-side. One domain for a human, the same as Prometheus already is.

### What the app writes

`libs/logs.py` picks the format from whether anything is reading by eye: **text on a TTY** (`make
dev`), **JSON everywhere else** (a container). JSON matters because `| json` in LogQL extracts fields
at query time for free, where plain text needs a `| pattern` expression re-derived per query and
re-broken every time a message changes shape.

```
{"ts": "...+00:00", "level": "WARNING", "logger": "tp_api", "msg": "initiate-plan places lookup failed ..."}
```

The worker was already well instrumented — a named logger per module, and `worker.py` logs every
task's full result dict on success and its `TaskError` on failure, which is why the per-handler loggers
in `rednote/` and `youtube/` have no call sites. That is deliberate, not a gap. `tp_api` had nothing at
all, and now logs the decisions an access log cannot show: whether a city was warm or queued a run,
why a Places call became a 502, whether a draft was queued or already running. uvicorn still logs a
line per request, so none of these repeat method, path or status.

`fileConfig` in `libs/db/migrations/env.py` passes `disable_existing_loggers=False`. Alembic's default
is `True`, which disables every logger already created — harmless while `migrate` is its own container,
fatal the first time a migration runs in the same process as the app.

### Labels

**`service` is the only label, and it is the compose service name.** Same rule as `route` on the
metric, for the same reason: Loki indexes labels and nothing else, so each unique label combination is
a separate stream with its own in-memory chunk. A container id would mint a new stream on every
restart. Trip ids live in the line, where `| json` still filters on them at zero index cost:

```logql
{service="api"}                                            # everything the API said
{service="api"} | json | level="WARNING"                   # fields, no index
{service="api"} | json | msg=~".*trip=abc12345.*"          # a single trip, unindexed
sum by (service) (rate({service=~"api|worker"} [5m]))      # a Prometheus-shaped query over logs
```

Alloy discovers containers over the Docker socket rather than tailing
`/var/lib/docker/containers/*/*-json.log`: that path only exists on a Linux host, and it yields the
container id, not a name. Discovery also scopes collection to this compose project, because the daemon
would otherwise hand over every container on the machine — including unrelated projects on a laptop.

Retention is 90 days, matching Prometheus, and needs the compactor's `retention_enabled: true` —
without it `retention_period` is advisory and the disk grows forever.

## Running it

```bash
make dev              # or make api — the API must be up to be scraped
make observability
```

Grafana is on <http://localhost:3001> with the *API latency* dashboard already provisioned and both
datasources wired; Prometheus is on <http://localhost:9090/targets>, which is where you confirm the
scrape is actually working. All of it binds to loopback only, so a public box does not serve them. Stop
them with:

```bash
make observability-down                 # keeps both volumes, so history survives the next start
make observability-down KEEP_DATA=0     # also removes them, discarding every metric and every log
```

The scrape target is `host.docker.internal:8000` for both ways the API runs: under `make dev` it is a
host process, and in the deployed stack the `api` container publishes `8000:8000` to the host. One
config, no second copy to drift.

**Logs are the exception to that.** `dev.sh` runs uvicorn and the worker as host processes, so there is
no container for Alloy to read and `make dev` sends nothing to Loki — your terminal is the log viewer
locally, which is also why the format stays human-readable on a TTY.

`make dev-container` is what fills Loki up locally: the same `docker-compose.yml` the box runs, so
`{service="api"}` and `{service="worker"}` answer for real. It has no reload, which is the point — the
image is what ships. See *Two ways to run it* in `docs/deploy.md`.

Grafana's dashboards and datasources are provisioned from the files in `observability/grafana/`, so
they are diffable and the UI is read-only. Edit the JSON, not the browser.

## Not done yet

- **The worker.** `python -m tp_ingestions` has no HTTP server, so scraping it means running
  `prometheus_client`'s own server inside the process. That is where this project's interesting
  numbers are: task duration by kind, throttle waits, Gemini calls. Queue depth should be a gauge
  that queries Postgres at scrape time, not a counter — Postgres already owns that state, which makes
  it restart-proof for free.
- **Multi-process uvicorn.** In-process counters are correct only because `api` runs single-process.
  Adding `--workers` needs `PROMETHEUS_MULTIPROC_DIR` and a `MultiProcessCollector`.
- **Unhandled 500s.** The middleware records the response it gets, so `HTTPException` (404, 422, 502)
  is counted but a handler that raises outright is not. Fine for now; the error-rate panel is about
  the errors the API means to return.
- **Alerting.** No Alertmanager. The dashboard is for looking at, not for paging.
- **No logs dashboard.** Loki is wired as a datasource and answered from Explore; nothing in
  `observability/grafana/dashboards/` shows a log panel next to the latency panels yet. That, plus a
  data link from `p95 by route` to the matching `{service="api"}` query, is the correlation this was
  built for.
- **Traces.** Tempo is the third datasource, and `trace_id` belongs in Loki's *structured metadata*
  rather than in a label — no cardinality cost, queryable without parsing the line. Loki is already on
  tsdb/schema v13, which is what allows it.
- **Cost, if this ever leaves a laptop.** Self-hosted Loki is near-free per byte but costs a stateful
  service and a volume you must not lose. On a private-subnet EC2 box shipping under ~700 MB/day,
  `awslogs` straight to CloudWatch is cheaper than the instance Loki would run on — and Grafana has a
  CloudWatch datasource, so the single pane survives either choice.
