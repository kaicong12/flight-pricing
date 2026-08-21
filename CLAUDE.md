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

Built so far: `tp_backend/libs/db` (schema + migrations), `tp_backend/tp_api`, the
`tp_backend/tp_ingestions` worker **through `places.resolve`**, and `tp_client` (the "plan a city
trip" screen). The pipeline now ends at a `place_id`: extractions fan out to `places.resolve`, which
writes `places` + `place_mentions`. Ranking and the itinerary screen are next.

`docker-compose.yml` runs migrate + api + **one** worker on a t4g.micro against RDS; `tp_client` is on
Vercel, so there is no `web` service. One worker, not one per source: `queue.claim` has no `kind`
filter and a throttle wait goes back to the queue, so nothing starves. `./dev.sh` runs both locally.
See `docs/deploy.md`.

# Conventions

**Comments and docstrings.** Minimal; code should read on its own. One or two lines at the top of a
file, one or two per function. Nothing else unless a line is genuinely non-obvious — a workaround, a
surprising API behaviour, a constraint invisible from the code — and then one short comment, not a
paragraph. No section banners, restatements, usage examples, or rationale essays: those belong here
or in the commit message.

**Docs.** This file is the only planning reference: decisions, what works, and gotchas that would cost
time to rediscover. Keep it short and prune it when things change — it is not a research log.

**Spikes.** Throwaway exploration lives in `spikes/<topic>/`. Secrets stay in the repo-root `.env`
(gitignored); scripts walk up to find it rather than holding their own copy.

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
data (doesn't exist), **Google Route Optimization** (no TRANSIT mode; time windows constrain arrival
only; skip reasons can't distinguish "closed" from "unreachable"), Tokyo/Bangkok/Singapore open data
(stale or geo-blocked).

## RedNote

`webapi.rednote.com`, endpoints `/api/sns/web/v1/search/notes` and `/api/sns/web/v1/feed`.

- **Auth needs a cookie AND a signature**, and the signature is **bound to the URL path** — one
  capture per endpoint, kept in `.env`. The signature does not expire; the cookie does, so the only
  maintenance is **cookie rotation**.
- **Rate limit hard** — it is a real logged-in account. Never on a request's critical path: build a
  background city pool, not per-plan ingestion.
- **Extract from the note `desc` first**; OCR the image cards only when `desc` names nothing (~38% of
  notes, ~10x the tokens). Take search results in returned relevance order, not by likes.
- **Geofence results** on the searched area — names resolve to the wrong side of a city otherwise.
- **Gate on what the note says, never on the Google rating.** Drop `not_recommended`, filter chains,
  and treat a Chinese name resolving to an English Places result as unconfirmed identity.
- Persist notes by `note_id` and never re-fetch; key extractions on `(note_id, prompt_version, model)`.
- **Searching with the English city name works.** `"Tromsø 美食"` returned 20 usable notes, titled
  with the Chinese exonym 特罗姆瑟. No need to translate the city name before searching.
- **Some `desc` values interleave zero-width characters between the letters of a venue name**
  (`T​a​n​g's`), which wrecks extraction. Strip Unicode category `Cf` before
  extracting; keep `Cc`, since newlines are the post's paragraph structure.
- On `/feed`, the English body is `note_translation.desc_trans` (not `desc_en`), `time` is epoch
  **milliseconds**, tags are `tag_list[].name`, and there is **no `ip_location`**.
- Cap the fetch fan-out (`rednote_max_fetch_per_search`, default 8): a search returns 20, so an
  uncapped fan-out spends most of an hour's budget on one city.

# Working pipeline

The real path is now the worker: `POST /initiate-plan` seeds `youtube.search` (one per language) and
`rednote.search`, whose handlers fan out per video and per note. `rednote.fetch` calls extraction
**inline as a child call**, so a note's body and its extraction commit together; OCR is a separate
task, queued only when the `desc` named nothing. `python -m tp_ingestions --report <run_id>` prints
what a run actually extracted.

Proven live on Tromsø, Bergen and Porto (~36 tasks each, 0 failed, 0 blocked): Tromsø's 122
candidates became 84 `searchText` calls and 58 places with 90 mentions. Run the worker with
`python -m tp_ingestions`, **not `--once`** — a throttle wait goes back to the queue via `run_after`
and `drain()` exits as soon as nothing is due.

## Budgets

One `Throttler` per domain (`tp_ingestions/throttle.py`), built in `limits.py` from `settings.py`: a
jittered gap plus any number of sliding windows. RedNote 50/h + 300/day behind 45s ± 15s; Gemini
15/min + 1000/day behind 4s. Places and YouTube are unthrottled — Places sits behind `place_queries`,
YouTube's `search.list` is one call per language per city.

- History is `throttle_calls` in **Postgres, not a file**: one shared account must not become one
  budget per host. `take()` checks and spends under `pg_advisory_xact_lock`, making it a reservation —
  a caller that then fails has still spent the slot, the safe way to be wrong.
- The spend commits on the throttler's **own connection**. Written in the handler's session, a failed
  task would roll it back and refund a call the remote already served.
- A wait under `max_inline_wait` **blocks the single-threaded worker** (10s RedNote; 60s Gemini,
  because deferring extraction inside `rednote.fetch` would re-spend a RedNote call). Longer defers.

## Resolving names to places

`places.resolve` turns one extraction's candidates into `places` + `place_mentions`.
`--resolve-preview <run_id>` shows what would be queried and dropped and calls nothing;
`--resolve-run <run_id>` then queues the real work over a finished run's extractions.

`place_queries` (`city_id`, `query_norm`) → `place_id` caches **hits only**, which is what makes
repeat resolution *guaranteed* rather than likely: a cached name never reaches Google, so it cannot
come back different.

- **A miss is deliberately not cached.** `searchText` answers a silent throttle with 200 and an empty
  list, indistinguishable from "no such place", so caching it would poison that name permanently.
  Re-paying is cheaper: a second Tromsø pass costs 9 calls, not 84. An in-task set stops one name
  costing two calls in one extraction.
- Unresolved candidates are logged and dropped — `places.place_id` is the PK, so there is no row for
  a place without an id. Districts (`Ribeira`, `Bergen city center`) resolve with zero ratings and are
  rejected on purpose: no hours, no single point to route to.

Spikes, superseded by the worker except for routing:
`spikes/routes_planning/route_day.py` runs `optimizeWaypointOrder: false` and validates against real
hours and daylight — *"Uspenski: arrive 15:43, need 75 min, closes 16:00"*. Also
`spikes/videos_transcribing/`, `spikes/xhs/`, `spikes/flights/`, `spikes/places_resolve/`.

# Gotchas

**Identity**
- **`place_id` is the identity, never the name.** `Vanha Kauppahalli`/`Old Market Hall` collapse to
  one id, as do six ASR spellings of `Fjellheisen`. The LLM renames things run to run even at
  temperature 0 — dedupe on the id and that stops mattering.
- **`locationRestriction` takes a `rectangle` only — a `circle` is a hard 400.** Circle is
  `locationBias`-only. A 400 is terminal, so this kills the task instead of retrying.
- **Always query `"<name>, <city>"`, even inside the box.** The box constrains geography, the suffix
  anchors the matcher. Bare `Tromso Cathedral` returns the **Arctic Cathedral**, a different building.
- **A bare generic noun resolves to a real, excellent venue and nothing in the response says so** —
  `bakery` → Vervet Bakeri 4.7 (553). So junk must be gated **before** the call. Check the *returned*
  name against the chain list too: `Storgata` is a street that resolves to the EUROSPAR on it.
- **Never reject on place type.** `Fjellheisen`, Tromsø's top attraction, has an empty
  `primaryTypeDisplayName`. Confidence comes from `userRatingCount`; zero ratings → reject.
- **Google itself carries duplicate listings** — `Raketten Bar & Pølse` at two `place_id`s, 1626 vs 83
  ratings. So `place_id` is necessary but not sufficient; v1 surfaces both for the user to delete one,
  because a legitimate two-branch chain looks identical.
- **Sanity-check coordinates against the city box.** `Sentra` (an ASR garble) resolved 350 km away.

**Queue**
- **A throttle wait must not spend an attempt.** `queue.claim` increments `attempts` on every claim,
  so deferring on *our own* budget burned retries — a Tromsø run lost 3 of 8 fetches to
  `max_attempts` with nothing wrong. Hence `errors.Throttled` + `queue.reschedule`, which decrements
  it back; a RATE_LIMITED `TaskError` means the *remote* pushed back and still counts.
- Reviving tasks in an already-settled run leaves the run stuck: `finish_run_if_done` only settles a
  run that is still `pending`/`running`. Reset the run's status too.

**Extraction**
- **Gemini `responseSchema` takes only an OpenAPI-3.0 subset** — no `$ref`, `oneOf`,
  `additionalProperties`, or string `format`. A violation is a 400, which is terminal, so a schema
  edit that breaks it kills the task rather than retrying. Image MIME must be sniffed from magic
  bytes: RedNote CDN URLs end `.jpg` while serving WebP.
- The model is `GEMINI_MODEL`, resolved per call via `Prompt.model`, so it can be swapped when a free
  tier runs out. It lands in `extractions.model`, which is part of the uniqueness key — **swapping
  the model re-extracts everything.**
- **`youtube-transcript-api` 1.x is instance-only.** `YouTubeTranscriptApi.get_transcript` and
  `TooManyRequests` are both gone; it is `YouTubeTranscriptApi().fetch()`, `RequestBlocked` and
  `IpBlocked`. `PoTokenRequired` is what a **datacenter IP** gets, so it maps to RATE_LIMITED, not
  PERMANENT — it is an environment problem, not a bad video.
- **`is_travel_content` gate is mandatory.** Without it a tennis vlog returned 7-Eleven and Haneda
  Airport as recommendations. Also exclude chains, transport hubs and cities-as-places.
- **Never take facts from ASR.** A €3.20 fare came through as "320 euros". Prices and hours come from
  Places; transcripts supply why-go prose only.
- **City-name gate must be able to return zero.** "Kutaisi Georgia" returned five videos that passed
  every filter, none about Kutaisi.
- Prefer videos whose captions are `MANUAL` — human subtitles have none of the ASR corruption.
- Query in local languages, per city. Corpora are fully disjoint; Japanese doubles Tokyo's yield.
  Skip Thai, English already wins Bangkok.
- `search.list` is capped at 100 calls/day in its own bucket. ~50 cities/day, divided per language.
- 30-day refresh-or-delete on any cached YouTube text.

**Routing**
- **TRANSIT does not support intermediate waypoints** — HTTP 400. Walking is one call for the whole
  day; transit is one call per consecutive pair.
- **TRANSIT has a ~100-day horizon.** `ROUTE_NOT_FOUND` beyond it. A trip booked months out can only
  be planned on walking times, firming up as the date approaches.
- **WALK silently routes through the Suomenlinna ferry** at 19 km/h, tagged as a toll — zero wait, no
  timetable. Special-case scheduled ferries.
- `computeRoutes` allows 25 intermediates; `computeRouteMatrix` caps at 625 elements, **100 for
  TRANSIT**. Transit times are time-dependent, so compute per plan rather than caching per city.
- Keep field masks minimal — they set the billing tier. Transit step details cost more.
- Check `arrival + duration` against closing time, not arrival alone.

**Hours and dates**
- **Holiday hours for a future date are unavailable.** `currentOpeningHours.specialDays` covers only
  the coming week, so a December plan built in August cannot know about Independence Day closures.
  **Label such plans provisional and re-check nearer the date.**
- Places `periods[].open.day` is 0=Sunday, but `weekdayDescriptions` is Monday-first. Off-by-one trap.
- `currentOpeningHours` differs from `regularOpeningHours` structurally (extra `date` fields) even
  when the hours are identical. Don't diff them naively.
- Outdoor blocks need a daylight check. Helsinki in early December has ~6h10m of light.

**Client**
- The browser never calls `tp_api`. Next route handlers proxy it, so there is no CORS middleware to
  maintain and no Google key in client JS. `TP_API_URL` is the only knob.
- **`shadcn` defaults to Base UI now, not Radix.** `components.json` says `base-nova`; `Popover` is
  `@base-ui/react` and only `Command` is still `cmdk`. Size a popup to its trigger with
  `w-(--anchor-width)`, not Radix's variable.
- **`shadcn init`/`add` need `NODE_EXTRA_CA_CERTS` and exit 0 when TLS interception blocks them**, so
  a chained `&&` sails past the failure. Check the files actually landed.
- `create-next-app` names its Geist variable `--font-geist-sans` but shadcn's `globals.css` expects
  `--font-sans`, so every page silently renders in the browser serif until you rename it.
- The React Compiler lint rule bans synchronous `setState` in an effect body, which rules out the
  obvious debounce shape. Derive state from a stamped result instead.

**Environment**
- **Corporate TLS interception breaks Python but not curl.** The intercepting root is in the OS store,
  which curl uses and certifi does not — `webapi.rednote.com` fails with `CERTIFICATE_VERIFY_FAILED`
  while `googleapis.com` succeeds, so it looks host-specific rather than trust-specific. All outbound
  HTTP goes through `libs/http.py`, which verifies via `truststore` (OS store), with
  `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` as an override. Node needs `NODE_EXTRA_CA_CERTS`.
- **Only the registry pull needs a workaround; the build does not.** Interception is selective, so
  pypi.org verifies inside a container and `uv sync` needs nothing — but *dockerd* resolves base
  images against the **host** trust store, which a Dockerfile cannot patch, hence `DOCKER_REGISTRY`
  pointing at an internal mirror. `tp_backend/certs/*.crt` (gitignored, dropped in locally) is for
  **runtime** egress to `webapi.rednote.com`. Both are no-ops on EC2.
- **Do not point uv at a different index.** `uv.lock` pins pypi.org URLs, so `UV_INDEX_URL` makes
  `uv sync --locked` fail on a lockfile it wants to rewrite. Pin `UV_VERSION` to the uv that wrote
  the lock for the same reason.
- Only `api` carries a `build:` section. All three services share one tag, and building it three
  times races on export — `image "tp-backend:local": already exists`, after a successful build.
- **Behind PgBouncer in transaction mode, set `connect_args={"prepare_threshold": None}`.** psycopg3
  prepares a statement after 5 executions, and transaction pooling breaks those. Not set today — we
  connect straight to Postgres. Web and worker each hold their own pool, so size them together.
- Rate limits are often *silent* — one API returned "0 results" while throttling. Always distinguish
  throttled from empty.
- `place_id` may be cached indefinitely; almost nothing else from Places may be.
- Tests must never reach the network — an autouse fixture in `tests/conftest.py` blocks
  `httpx.HTTPTransport` and `requests`' adapter, so a stub that misses fails loudly instead of
  quietly spending quota. TestClient rides ASGITransport and is unaffected.
- `conftest` derives one fixed `<database_url>_test` and truncates at every test start, so two
  concurrent `pytest` runs wipe each other's rows mid-test.
- Alembic's `env.py` calls `fileConfig()` without `disable_existing_loggers=False`, so running
  migrations in-process silences every logger imported before it.
- `import libs.db.session` binds the re-exported `session` **function**, not the submodule. Reach it
  with `importlib.import_module`.

The transit 100-day horizon and unfetchable future holiday hours are load-bearing for the roadmap: a
trip planned in August cannot be fully accurate for December, so the UI needs a
re-check-nearer-the-date affordance rather than presenting an early plan as final.

# Open items

1. **Nothing exposes `places`.** The API has `/cities/search`, `/initiate-plan` and
   `/trips/{id}` (progress counts only), so the UI can watch an ingestion finish but cannot show its
   result. A shortlist endpoint ranked by mention count is the next thing to build. `GET /trips` is
   missing too, so the trips list renders its empty state.
2. **Enable Routes API** on the existing key, and restrict the key to Places + Routes + YouTube + Gemini.
3. **Confirm Places and Routes pricing** and whether caching lat/lon is permitted. Resolution is now
   the biggest spender: 84 `searchText` calls on one city, on the field mask that includes
   `userRatingCount`.
4. **Test transcript fetching from cloud egress**, not just a laptop. Confirmed working from a laptop;
   the failure mode to watch for on EC2 is `PoTokenRequired`.
5. A real `GET /health` for the container healthcheck, which currently probes `/openapi.json`.
6. **The generic-noun and chain stoplists in `tp_ingestions/places/names.py` are Norway-leaning.**
   They will need a pass per new country; `--resolve-preview` is the free way to check one.
