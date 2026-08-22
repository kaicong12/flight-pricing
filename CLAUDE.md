# Trip Planner

User enters a city, dates, flight times and one sentence about themselves. We shortlist places from
travel videos and posts, show them as a list beside a map, and the user drags them into order. We
route that exact sequence and warn about anything that doesn't work.

**We do not optimise the order.** The user controls it; our job is routing plus validation.

| | |
|---|---|
| Audience | Private group of friends |
| Output | Ordered activity blocks + a route drawn on a map |
| Collaboration | One owner; others propose edits; owner approves |
| Flights | Input only in v1 |
| Cities | Any city on demand — async ingestion, client polls |
| Stack | Next.js + Postgres, TypeScript web, **Python worker** (keeps the spike scripts) |
| Queue | Postgres `SKIP LOCKED`. Not `pg-boss` (Node-only). No Redis — the work is quota-bound |
| Deploy | Railway/Render/Fly first, EKS later |

# The data flow

One trip, end to end. Everything after the POST is asynchronous; the client polls.

```
browser → Next route handler → tp_api → Postgres queue → tp_ingestions worker → Postgres
                                  ↑                                                 │
                                  └──────────── client polls /trips/{id} ───────────┘
```

**1. Create.** `POST /initiate-plan` resolves the city through Google Places, writes a `trips` row,
and calls `ensure_city_ingest`. A city ingested within `city_refresh_days` (30) is warm and queues
nothing; otherwise this creates one `ingest_runs` row plus its seed tasks. Two friends planning the
same city join one run — a unique index on active runs per city enforces that.

**2. Discover.** The worker claims tasks with `FOR UPDATE SKIP LOCKED`. Seed tasks are
`youtube.search` (one per language) and `rednote.search`; their handlers fan out one task per video
and per note. One worker, not one per source: `queue.claim` has no `kind` filter and a throttle wait
goes back to the queue, so nothing starves.

**3. Extract.** `youtube.extract` pulls a transcript; `rednote.fetch` pulls a note body and calls
Gemini **inline as a child call**, so body and extraction commit together. OCR is a separate task,
queued only when the note's `desc` named nothing. Output is candidate place *names* in
`extractions` — prose and opinion only, never facts.

**4. Resolve.** `places.resolve` turns one extraction's candidates into `places` + `place_mentions`
via Places `searchText`. **`place_id` is the identity, never the name** — that is what makes two
sources naming one venue count once, and what makes the LLM's run-to-run renaming stop mattering.
`place_queries` caches hits only, so a repeat pass over a city is cheap.

**5. Watch.** `GET /trips/{id}` returns the trip plus a group-by of its tasks; `GET /trips` returns
one row per trip for the list. The client polls until the run reaches a terminal status.

Ranking and the itinerary screen are next; routing exists only as a spike.

## Budgets

One `Throttler` per domain, built in `limits.py` from `settings.py`: a jittered gap plus sliding
windows. RedNote 50/h + 300/day behind 45s ± 15s; Gemini 15/min + 1000/day behind 4s. Places and
YouTube are unthrottled. History lives in `throttle_calls` in **Postgres, not a file** — one shared
account must not become one budget per host.

## Where the code is

| | |
|---|---|
| `tp_backend/libs/db` | Schema + migrations |
| `tp_backend/tp_api` | The API |
| `tp_backend/tp_ingestions` | The worker, through `places.resolve` |
| `tp_client` | `/` (form), `/trips` (list), `/trip/{trip_id}` (dates + live checklist) |
| `spikes/<topic>/` | Throwaway exploration; routing still lives here |

`./dev.sh` runs migrate + api + worker locally. `docker-compose.yml` runs the same three on a
t4g.micro against RDS; `tp_client` is on Vercel, so there is no `web` service. See `docs/deploy.md`.

Run the worker as `python -m tp_ingestions`, **not `--once`**: a throttle wait goes back to the queue
via `run_after` and `drain()` exits as soon as nothing is due.
`python -m tp_ingestions --report <run_id>` prints what a run actually extracted.

Proven live on Tromsø, Bergen, Porto and Singapore (~36 tasks each). Tromsø's 122 candidates became
84 `searchText` calls and 58 places with 90 mentions.

# Sources

| Role | Source |
|---|---|
| Discovery | **YouTube** — transcripts primary, chapters as spelling anchor, comments |
| Food + POI | **RedNote/Xiaohongshu** — private web API, confirmed usable |
| Identity + facts | **Google Places** `searchText` → `place_id`, then Place Details for hours |
| Routing + map | **Routes API `computeRoutes`** — polyline, per-leg times, transit steps |
| Daylight | Computed locally (NOAA), no API |
| Thin-city fallback | **Wikivoyage**, labelled guidebook-grade |
| Later | Reddit, behind a disabled flag |

Ruled out: Reddit (blocked), OSM/Overture/Wikidata (inventories, no curation signal), Foursquare open
data (doesn't exist), **Google Route Optimization** (no TRANSIT mode; skip reasons can't distinguish
"closed" from "unreachable"), Tokyo/Bangkok/Singapore open data (stale or geo-blocked).

# Conventions

**Comments and docstrings.** Minimal; code should read on its own. One or two lines at the top of a
file, one or two per function. Nothing else unless a line is genuinely non-obvious — a workaround, a
surprising API behaviour, a constraint invisible from the code — and then one short comment, not a
paragraph. No section banners, restatements, usage examples, or rationale essays.

**Docs.** This file is the planning reference: the flow, the decisions, what works. Keep it short and
prune it when things change — it is not a research log. The detail that would cost a debugging
session to rediscover lives in `docs/gotchas.md`; **read that before touching a source integration,
the queue, or Places.** Visual language is `tp_client/docs/design-system.md`.

**Spikes.** Throwaway exploration lives in `spikes/<topic>/`. Secrets stay in the repo-root `.env`
(gitignored); scripts walk up to find it rather than holding their own copy.

# What constrains the roadmap

Transit routing has a ~100-day horizon and future holiday hours are unfetchable, so a trip planned in
August cannot be fully accurate for December. The UI needs a re-check-nearer-the-date affordance
rather than presenting an early plan as final.

# Open items

1. **Nothing exposes `places`.** `GET /trips` carries a `place_count`, but that is a count and not
   the list. A shortlist endpoint ranked by mention count is the next thing to build.
2. **Enable Routes API** on the existing key, and restrict the key to Places + Routes + YouTube + Gemini.
3. **Confirm Places and Routes pricing** and whether caching lat/lon is permitted. Resolution is the
   biggest spender: 84 `searchText` calls on one city.
4. **Test transcript fetching from cloud egress**, not just a laptop. The failure mode to watch for
   on EC2 is `PoTokenRequired`.
5. A real `GET /health` for the container healthcheck, which currently probes `/openapi.json`.
6. **The generic-noun and chain stoplists in `tp_ingestions/places/names.py` are Norway-leaning.**
   They will need a pass per new country; `--resolve-preview` is the free way to check one.
