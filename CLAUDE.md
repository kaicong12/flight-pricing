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
`tp_backend/tp_ingestions` worker through extraction, and `tp_client` (the "plan a city trip"
screen). `places.resolve` is the next step — extractions land in `extractions.result` as JSON and
nothing writes `places`/`place_mentions` yet.

`docker-compose.yml` runs migrate + api + **one** worker + web on a single t4g.micro against RDS.
One worker, not one per source: `queue.claim` has no `kind` filter and the RedNote throttle hands
long waits back to the queue, so nothing starves. See `docs/deploy.md`.

# Conventions

## Comments and docstrings

Keep them minimal. Code should read on its own.

- One or two lines at the top of a file saying what it is.
- One or two lines per function saying what it does.
- Nothing else, unless a line is genuinely non-obvious — a workaround, a surprising API behaviour,
  or a constraint that isn't visible from the code. Then one short comment, not a paragraph.

Do not write: section banners (`# ---- setup ----`), restatements of the code, usage examples in
docstrings, rationale essays, or explanations of design decisions. Those belong in this file or the
commit message.

## Docs

This file is the only planning reference: decisions, what works, and gotchas that would cost time to
rediscover. Keep it short and prune it when things change — it is not a research log.

## Spikes

Throwaway exploration lives in `spikes/<topic>/`. Secrets stay in the repo-root `.env` (gitignored);
scripts walk up to find it rather than holding their own copy.

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
- Cap the fetch fan-out (`rednote_max_fetch_per_search`, default 8): a search returns 20 and
  `MAX_PER_HOUR` is 20, so an uncapped fan-out spends a whole hour's budget on one city.

# Working pipeline

The real path is now the worker: `POST /initiate-plan` seeds `youtube.search` (one per language) and
`rednote.search`, whose handlers fan out per video and per note. `rednote.fetch` calls extraction
**inline as a child call**, so a note's body and its extraction commit together; OCR is a separate
task, queued only when the `desc` named nothing. `python -m tp_ingestions --report <run_id>` prints
what a run actually extracted.

Proven live end-to-end on Tromsø: 22 tasks, 0 failed, 122 candidate places (11 RedNote, 111 YouTube)
for 19 Gemini calls and about a cent. Run the worker with `python -m tp_ingestions`, **not `--once`**
— RedNote waits are handed back to the queue via `run_after`, and `drain()` exits as soon as nothing
is due.

The original spike scripts, joined by JSON files on disk:

```bash
python youtube_search.py Helsinki --lang en --region FI --out videos.json
python youtube_llm_pipeline.py <id> --json places.json      # gemini-3.5-flash-lite + JSON schema
python resolve_places.py places.json --hours --out resolved.json
python route_day.py resolved.json --date 2026-12-06 --start 10:00 --mode walk --out day.json
```

`route_day.py` runs with `optimizeWaypointOrder: false`, returns an encoded polyline, per-leg
durations and transit steps (`2: Kauppatori -> Lasipalatsi`), and validates against real hours and
daylight — e.g. *"Uspenski: arrive 15:43, need 75 min, closes 16:00"*.

`spikes/videos_transcribing/` — `youtube_search.py`, `youtube_llm_pipeline.py`, `resolve_places.py`
`spikes/routes_planning/` — `route_day.py`
`spikes/xhs/` — `recommend.py` (city → restaurants), `food_spike.py`, `image_ocr.py`, `call.py`
`spikes/flights/` — earlier Google Flights price-tracking spikes

# Gotchas

**Identity**
- **`place_id` is the identity, never the name.** `Vanha Kauppahalli`/`Old Market Hall` and
  `Löyly`/`Loyly` collapse to one id. The LLM returns different names across runs even at
  temperature 0 — dedupe on the id and that stops mattering.
- **Sanity-check resolved coordinates against a city bounding box.** `Sentra` (an ASR garble)
  resolved to a business 350 km away.
- **Confidence from `userRatingCount`, not name similarity.** Zero ratings → reject. Deaccent before
  comparing names.

**Queue**
- **A throttle wait must not spend an attempt.** `queue.claim` increments `attempts` on every claim,
  so deferring a task because *our own* budget said "not yet" burned its retries: a live Tromsø run
  lost 3 of 8 RedNote fetches to `max_attempts` with nothing actually wrong. Hence
  `errors.Throttled` + `queue.reschedule`, which decrements `attempts` back. A RATE_LIMITED
  `TaskError` still means the *remote* pushed back and still counts.
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

The two load-bearing findings for the roadmap are the transit 100-day horizon and holiday hours being
unfetchable for future dates. A trip planned in August genuinely cannot be fully accurate for
December, so the UI needs a re-check-nearer-the-date affordance rather than presenting an early plan
as final.

# Open items

1. **`places.resolve`** — turn `extractions.result` candidates into `places` + `place_mentions`. The
   live run shows why it matters: `Raketten Bar & Pølse` (RedNote) and `Raken Bar and Pulse`
   (YouTube ASR) are one venue, and `Pastafabrikken` was recommended by two separate notes.
2. **Enable Routes API** on the existing key, and restrict the key to Places + Routes + YouTube + Gemini.
3. **Confirm Places and Routes pricing** and whether caching lat/lon is permitted.
4. **Test transcript fetching from cloud egress**, not just a laptop. Confirmed working from a laptop;
   the failure mode to watch for on EC2 is `PoTokenRequired`.
5. A real `GET /health` for the container healthcheck, which currently probes `/openapi.json`.
