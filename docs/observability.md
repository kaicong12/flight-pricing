# Observability

One metric, scraped from the API. `make observability` brings up Prometheus and Grafana; the backend
stack in `docker-compose.yml` is untouched and still fits a t4g.micro.

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

## Running it

```bash
make dev              # or make api — the API must be up to be scraped
make observability
```

Grafana is on <http://localhost:3001> with the *API latency* dashboard already provisioned; Prometheus
is on <http://localhost:9090/targets>, which is where you confirm the scrape is actually working.
Both bind to loopback only, so a public box does not serve them. Stop them with:

```bash
make observability-down                 # keeps the TSDB, so history survives the next start
make observability-down KEEP_DATA=0     # also removes the volumes, discarding every metric
```

The scrape target is `host.docker.internal:8000` for both ways the API runs: under `make dev` it is a
host process, and in the deployed stack the `api` container publishes `8000:8000` to the host. One
config, no second copy to drift.

Grafana's dashboard and datasource are provisioned from the files in `observability/grafana/`, so the
dashboard is diffable and the UI is read-only. Edit the JSON, not the browser.

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
