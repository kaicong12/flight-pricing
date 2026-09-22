# Trip Planner

User enters a city, dates, flight times and one sentence about themselves. We shortlist places from
travel videos and posts, show them as a list beside a map, and the user drags them into order. We
route that exact sequence and warn about anything that doesn't work.

**We do not optimise the order.** The user controls it; our job is routing plus validation.

| | |
|---|---|
| Audience | Private group of friends |
| Output | Ordered activity blocks + a route drawn on a map |
| Collaboration | `user_trips.role`: owner, editor, viewer. Editors edit the itinerary directly — no approval step |
| Auth | Google sign-in. Opaque session token in Postgres, not a JWT — sign out revokes |
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

**0. Sign in.** `tp_client` holds the session in an httpOnly cookie and forwards it as a bearer on
every proxied call; `tp_api` owns the Google exchange, because the client secret and the database
are both on that side. **The id_token's signature is deliberately not verified** — the code is
exchanged by us, over TLS, authenticated with our own client secret, which is the case Google says
needs no validation. That is what keeps a JWT library out of the dependencies. `place_id` is a
venue's identity and Google's `sub` is a person's, but `users.user_id` is our own uuid: sharing a
trip with a friend who has never signed in needs a row before any `sub` exists.

**1. Create.** `POST /initiate-plan` resolves the city through Google Places, writes a `trips` row,
and calls `ensure_city_ingest`. A city ingested within `city_refresh_days` (30) is warm and queues
nothing; otherwise this creates one `ingest_runs` row plus its seed tasks. Two friends planning the
same city join one run — a unique index on active runs per city enforces that.

**2. Discover.** The worker claims tasks with `FOR UPDATE SKIP LOCKED`. Seed tasks are
`youtube.search` (one per language) and `rednote.search`; their handlers fan out one task per video
and per note. One worker, not one per source: `queue.claim` has no `kind` filter and a throttle wait
goes back to the queue, so nothing starves.

**3. Extract.** The LLM is always its own step, because it is the flakiest one and must never roll
back a paid fetch: `rednote.fetch` stores the body and queues `rednote.extract`, and
`youtube.extract` commits the transcript before it calls Gemini. A failed extraction therefore
retries against stored text and spends no RedNote call. OCR is a separate task too, queued only when
the note's `desc` named nothing. Output is candidate place *names* in `extractions` — prose and
opinion only, never facts.

**4. Resolve.** `places.resolve` turns one extraction's candidates into `places` + `place_mentions`
via Places `searchText`. **`place_id` is the identity, never the name** — that is what makes two
sources naming one venue count once, and what makes the LLM's run-to-run renaming stop mattering.
`place_queries` caches hits only, so a repeat pass over a city is cheap.

**5. Watch.** `GET /trips/{id}` returns the trip plus a group-by of its tasks; `GET /trips` returns
one row per trip for the list. The client polls until the run reaches a terminal status.
`DELETE /trips/{id}` sets `trips.deleted`, which drops it from the list — soft, because the ordering
work is worth more than the row.

**5b. Share.** `user_trips.role` is the whole permission model: `require_trip_access` returns the
caller's role and `require_edit`/`require_admin` compose on top, so a role is checked where the route
is declared and `tests/test_auth.py` fails any trip write that forgets one. Owners rename, share and
delete; editors change the plan; viewers read. `GET /users/search` feeds the share dropdown,
`POST/DELETE /trips/{id}/members` writes it, and both trip payloads carry `your_role` so the client
hides what would only 403. Sharing is reachable from a trip card as well as the plan screen.

**6. Plan.** `GET /trips/{id}/shortlist` ranks the trip's places by mention count and returns each
mention as a link back to the video or note that named it. **The set is trip-scoped**: the city's
ingested places plus whatever this trip added by hand, which `trip_places` records — one predicate,
`service.in_shortlist`, that `replace_days` and `add_dismissal` share. `GET
/trips/{id}/places/search` and `POST /trips/{id}/places` add one the videos never named, from a modal
on the plan screen: autocomplete near the city, then Place Details on the pick, then the same
`places` row an ingestion would have written, claimed for this trip. **Nothing checks it is near the
city** — a place across the country is a legitimate thing to plan, because no distance is modelled
anywhere. It ranks last with no mentions, so the client prepends it. **A category is compulsory**, and
is the one thing `places.category` exists for: every other category is a majority vote over
`place_mentions`, which a hand-added place has none of, so without it the place is invisible under
every filter chip — and a set category is also what tells a hand-added place from an ingested one.
A person's answer beats the videos'. The user drags
them into days; `PUT /trips/{id}/itinerary` replaces whole days, because a drag is a statement about
a sequence and positions are dense and derived. `POST /trips/{id}/days/{n}/route` then checks that
exact order against Place Details hours and local daylight and returns structured warning codes — the
client owns the English. **Travel between blocks is not modelled at all** — not the time, not the
distance, not whether a route exists. A day may name two places on opposite sides of the world and
nothing objects; the map draws numbered pins and no line. `itinerary_items.reference_url` is the
user's own link on a block — a booking, a listing, a receipt — stored and opened, never fetched; the
plan screen edits it from the block itself and saving one does not re-check the day. `GET
/trips/{id}/export.xlsx` is those same days as a workbook: Itinerary, a band per day and the warning
in the app's own amber and clay, with a `Ref` column **only when some block has a link**, plus
Shortlist, whose `Source` column is the video or note that named the place. It re-reads hours, and
the warning English lives in `export.py` because a spreadsheet has no client to own it.

**7. Draft.** `route.plan` fills a trip's *empty* days so the plan screen opens filled — **one Gemini
call in a loop, not an agent**: the shortlist is already a closed ranked set and `plan_day` already
judges hours, so the model only proposes an arrangement and never goes looking. A day the user has
touched is theirs. It is queued automatically once (warm city at `/initiate-plan`, otherwise when the
city run settles DONE) and on demand by `POST /trips/{id}/draft`, which the plan screen's "Draft my
days" button calls. `GET /trips/{id}` reports the task as `draft` plus a progress row, which is what
the checklist polls — without it a draft in flight looks like a feature that does not exist.

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
| `tp_backend/libs/routing` | Hours, daylight and day validation. Pure except `hours.py` |
| `tp_client` | `/login`, `/` (form), `/trips` (list), `/trip/{trip_id}` (checklist), `/trip/{trip_id}/plan` (shortlist + days + map) |
| `spikes/<topic>/` | Throwaway exploration. `routes_planning` and `google_auth` are superseded by `libs/routing` and `libs/auth.py` |

`make dev` runs everything locally — migrate + api + worker via `./dev.sh`, plus the web app — and one
Ctrl-C stops all of it. `make dev-container` runs the same backend from `docker-compose.yml` instead,
with `docker-compose.local.yml` adding the `db` service RDS provides in production: no reload, but real
container DNS and its logs reach Loki. `DATABASE_URL` is the only difference between the two stacks.
`make help` lists the rest. `docker-compose.yml` runs the three backend
services on a t4g.micro against RDS; `tp_client` is on Vercel, so there is no `web` service. See
`docs/deploy.md`.

`make observability` adds Prometheus + Loki + Alloy + Grafana as an opt-in overlay. Prometheus scrapes
one histogram — `http_request_duration_seconds` — off the API's `/metrics`; Alloy pushes every
container's stdout into Loki. The app stores neither: those two volumes are what must survive.
**Metrics are pulled, logs are pushed** — so Prometheus tolerates a closed laptop and Loki does not.
`route` is the route template and `service` is the compose service name, never a path or a container
id: labels are indexed, so an unbounded one is what takes either store down. `libs/logs.py` writes
JSON off a TTY and text on one, because `| json` is free at query time. See `docs/observability.md`.

Run the worker as `python -m tp_ingestions`, **not `--once`**: a throttle wait goes back to the queue
via `run_after` and `drain()` exits as soon as nothing is due.

Proven live on Tromsø, Bergen, Porto and Singapore (~36 tasks each). Tromsø's 122 candidates became
84 `searchText` calls and 58 places with 90 mentions. The plan screen is proven against Tromsø
end to end: real opening hours and a `closes_before_done` warning. The trips
themselves were deleted when `user_trips` arrived, since they predate any owner — the cities and
places are city-scoped and stayed, so re-creating a Tromsø trip is warm and re-tests the same path.

# Sources

| Role | Source |
|---|---|
| Discovery | **YouTube** — transcripts primary, chapters as spelling anchor, comments |
| Food + POI | **RedNote/Xiaohongshu** — private web API, confirmed usable |
| Identity + facts | **Google Places** `searchText` → `place_id`, then Place Details for hours |
| Map | **MapLibre GL** with a keyless basemap — numbered pins, no route line |
| Daylight | Computed locally (NOAA), no API |
| Thin-city fallback | **Wikivoyage**, labelled guidebook-grade |
| Later | Reddit, behind a disabled flag |

Ruled out: Reddit (blocked), OSM/Overture/Wikidata (inventories, no curation signal), Foursquare open
data (doesn't exist), **Routes API `computeRoutes`** (a WALK polyline is meaningless the moment a
day spans two cities, and it answers a 3000 km leg with a route rather than a refusal),
Tokyo/Bangkok/Singapore open data (stale or geo-blocked).

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

Future holiday hours are unfetchable, so a trip planned in August cannot be fully accurate for
December. The UI needs a re-check-nearer-the-date affordance rather than presenting an early plan as
final.

# Open items

1. **Restrict the API key** to Places + YouTube + Gemini. Routes is no longer called at all.
2. **Confirm Places pricing** and whether caching lat/lon is permitted. Resolution is the biggest
   spender: 84 `searchText` calls on one city. `place_hours` now caches opening hours on a
   7-day TTL (`place_hours_ttl_days`), which is a judgement call about the terms, not a settled one.
3. **Test transcript fetching from cloud egress**, not just a laptop. The failure mode to watch for
   on EC2 is `PoTokenRequired`.
4. **The generic-noun and chain stoplists in `tp_ingestions/places/names.py` are Norway-leaning.**
   They will need a pass per new country, and there is no longer a dry-run that shows what a
   country's names would query or drop.
5. **`tp_client` has no test runner.** `src/lib/*.check.ts` are standalone instead — `npx tsx
   src/lib/plan-state.check.ts` covers the reducer, `plan-types.check.ts` the grid maths. Nothing
   runs them automatically, which is how `plan-types.check.ts` sat broken from 6ce4601 until it was
   noticed by hand. They want a `make` target at least.
6. **No pinned arrival times.** Durations are editable; block start times are always derived. The
   design's "booked 17:00" affordance needs a per-item locked time.
7. **Expired `sessions` rows are never collected.** Sign-out deletes its own row and a lapsed token
   stops resolving, but nothing sweeps the table. One `DELETE ... WHERE expires_at < now()` on a
   schedule, whenever the row count starts to matter.
8. **The Google hop itself is only verified by hand.** Everything either side of it is covered —
   `tests/test_auth.py` asserts the open-route set, so a new endpoint added without a session
   dependency fails the suite — but nobody can click Google's consent screen in CI.
9. **Sign-in has no rate limit.** `POST /auth/google` and `GET /auth/url` are open by necessity.
10. **Sharing has no invite for someone who has never signed in.** The dropdown searches `users`,
    so a friend must have signed in here once before they can be added. An email invite that creates
    the row first is the missing half — `users.user_id` is our own uuid precisely so it can exist
    before any Google `sub` does.
