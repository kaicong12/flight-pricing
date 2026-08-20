# Trip Planner

Enter a city, dates, flight times and one sentence about yourselves. We shortlist places from travel
videos and posts, show them as a list beside a map, and you drag them into order. We route that exact
sequence and warn about anything that does not work.

**We do not optimise the order.** The user controls it; our job is routing plus validation.

![Itinerary beside the map](screenshots/itinerary_and_map.png)

Day 1 in Helsinki: ordered blocks with the walk leg between each pair, a provisional-plan banner
because December holiday hours are not published yet, and a TOO LATE warning on Uspenski Cathedral —
arrive 15:43, need 30 minutes, closes 16:00. This screen is a **mockup, not a running app** — the
map pane is a placeholder until the Routes API is enabled.

## How it works

City -> `youtube.search` / `rednote.search` -> extract place names per video or note -> resolve each
to a Google `place_id` -> rank by how many independent sources mentioned it.

- `place_id` is the identity, never the name. That is what makes cross-source counting work.
- Ingestion is a **shared per-city pool**: two people planning the same city join one run (partial
  unique index on `ingest_runs`), and a city is only re-ingested after `city_refresh_days`.
- It is async. `POST /initiate-plan` returns a `run_id` immediately; the client polls
  `GET /trips/{trip_id}`, which returns task counts grouped by kind and status.
- Queue is Postgres, no Redis. Tasks are claimed `FOR UPDATE SKIP LOCKED`, `locked_at` is a lease so
  a dead worker's task is reclaimed rather than stuck, and backoff is chosen by error class.

## Status

| Works today | Not built |
|---|---|
| Schema + Alembic migrations | `places.resolve` — extractions land in `extractions.result` and nothing writes `places` yet |
| `POST /initiate-plan`, `GET /trips/{trip_id}` | Itinerary generation |
| Worker loop: claim, lease reclaim, retry/backoff | Routing in the app (spike only) |
| `youtube.search`, `rednote.search`, which fan out follow-on tasks | Every trip screen past the list: plan form redesign, ingesting, itinerary, sharing |
| Versioned Gemini prompts in `libs/prompts` | Auth, sharing, proposed changes |
| `tp_client`: the plan form and the trips list | |

## Getting started

A `uv` project rooted at `tp_backend/`. Needs Postgres and a repo-root `.env` (gitignored) holding
`DATABASE_URL`, `GOOGLE_API_KEY`, `GEMINI_API_KEY` and the `XHS_*` RedNote cookie/signature vars.

```bash
cd tp_backend
uv sync
uv run alembic -c libs/db/alembic.ini upgrade head
uv run pytest                            # creates and migrates <DATABASE_URL>_test
uv run uvicorn tp_api.main:app --reload
uv run python -m tp_ingestions           # worker; --once drains what is due and exits
```

The worker calls a real logged-in RedNote account with a hard rate limit. Do not run it idly.

## Layout

| | |
|---|---|
| `tp_backend/` | API (`tp_api`), worker (`tp_ingestions`), schema and shared code (`libs`) |
| `tp_client/` | Next.js app: route handlers proxy `tp_api`, so no key reaches client JS |
| `spikes/` | throwaway exploration joined by JSON files on disk, not production code |
| `screenshots/` | design mockups |

[CLAUDE.md](CLAUDE.md) is the planning reference: sources, decisions, and the gotchas worth reading
before touching routing or hours — TRANSIT takes no intermediate waypoints and has a ~100-day
horizon, and holiday hours for a future date cannot be fetched, so a December plan built in August is
labelled provisional.
