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

**6. Plan.** `GET /trips/{id}/shortlist` ranks the city's places by mention count. The user drags
them into days; `PUT /trips/{id}/itinerary` replaces whole days, because a drag is a statement about
a sequence and positions are dense and derived. `POST /trips/{id}/days/{n}/route` then routes that
exact order through `computeRoutes`, checks it against Place Details hours and local daylight, and
returns structured warning codes — the client owns the English.

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
| `tp_backend/libs/routing` | Routing, hours, daylight and day validation. Pure except `routes.py`/`hours.py` |
| `tp_client` | `/` (form), `/trips` (list), `/trip/{trip_id}` (checklist), `/trip/{trip_id}/plan` (shortlist + days + map) |
| `spikes/<topic>/` | Throwaway exploration. `routes_planning` is superseded by `libs/routing` |

`make dev` runs everything locally — migrate + api + worker via `./dev.sh`, plus the web app — and one
Ctrl-C stops all of it. `make help` lists the rest. `docker-compose.yml` runs the three backend
services on a t4g.micro against RDS; `tp_client` is on Vercel, so there is no `web` service. See
`docs/deploy.md`.

Run the worker as `python -m tp_ingestions`, **not `--once`**: a throttle wait goes back to the queue
via `run_after` and `drain()` exits as soon as nothing is due.
`python -m tp_ingestions --report <run_id>` prints what a run actually extracted.

Proven live on Tromsø, Bergen, Porto and Singapore (~36 tasks each). Tromsø's 122 candidates became
84 `searchText` calls and 58 places with 90 mentions. The plan screen is proven against Tromsø
end to end: real walking legs, real opening hours, and a `closes_before_done` warning.

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
prune it when things change — it is not a research log. Visual language is
`tp_client/docs/design-system.md`.

**Spikes.** Throwaway exploration lives in `spikes/<topic>/`. Secrets stay in the repo-root `.env`
(gitignored); scripts walk up to find it rather than holding their own copy.

# What constrains the roadmap

Transit routing has a ~100-day horizon and future holiday hours are unfetchable, so a trip planned in
August cannot be fully accurate for December. The UI needs a re-check-nearer-the-date affordance
rather than presenting an early plan as final.

# Open items

1. **Restrict the API key** to Places + Routes + YouTube + Gemini. (Routes itself is enabled and
   verified live, WALK and TRANSIT both.)
2. **Confirm Places and Routes pricing** and whether caching lat/lon is permitted. Resolution is the
   biggest spender: 84 `searchText` calls on one city. `place_hours` now caches opening hours on a
   7-day TTL (`place_hours_ttl_days`), which is a judgement call about the terms, not a settled one.
3. **Day routes are not cached.** Every first view of a day spends one `computeRoutes` call, so a
   page reload re-pays. The fix is a `day_routes` row keyed on a hash of (mode, date, ordered
   place_ids) so an unchanged order is free and a reordered day is marked stale rather than re-routed
   on a GET.
4. **Test transcript fetching from cloud egress**, not just a laptop. The failure mode to watch for
   on EC2 is `PoTokenRequired`.
5. **The generic-noun and chain stoplists in `tp_ingestions/places/names.py` are Norway-leaning.**
   They will need a pass per new country; `--resolve-preview` is the free way to check one.
6. **`tp_client` has no test runner.** The plan screen's reducer is exported pure precisely so it can
   be covered; a revision-handling bug in it wedged re-routing and only a browser caught it.
7. **No pinned arrival times.** Durations are editable; block start times are always derived. The
   design's "booked 17:00" affordance needs a per-item locked time.
8. **`packageManager` says yarn but `package-lock.json` is what is committed.** Pick one — Vercel
   reads `packageManager`, so the mismatch decides the deploy's resolver.
