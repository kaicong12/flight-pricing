# Trip Planner — Planning Notes

User enters a city, dates and flight times plus one sentence about themselves. We shortlist places
from YouTube travel videos, show them as a list beside a map, and the user drags them into the order
they want. We then route that exact sequence and warn about anything that doesn't work.

**We do not optimise the order.** The user controls it; our job is routing plus validation.

| | |
|---|---|
| Audience | Private group of friends |
| Output | Ordered activity blocks + a route drawn on a map |
| Collaboration | One owner; others propose edits; owner approves |
| Flights | Input only in v1 |
| Cities | Any city on demand — async ingestion, client polls |
| Stack | Next.js + Postgres, TypeScript web, **Python worker** (keeps the spike scripts) |
| Queue | Postgres — `procrastinate` or `SKIP LOCKED`. Not `pg-boss`: Node-only |
| Deploy | Railway/Render/Fly first, EKS later |

## Sources

| Role | Source |
|---|---|
| Discovery | **YouTube** — transcripts primary, chapters as spelling anchor, comments |
| Food + POI | **RedNote/Xiaohongshu** — private web API, confirmed usable |
| Identity + facts | **Google Places** `searchText` → `place_id`, then Place Details for hours |
| Routing + map | **Routes API `computeRoutes`** — polyline, per-leg times, transit steps |
| Daylight | Computed locally (NOAA), no API |
| Thin-city fallback | **Wikivoyage**, labelled guidebook-grade |
| Later | Reddit, behind a disabled flag |

Ruled out: Reddit (blocked), OSM/Overture/Wikidata (inventories, no curation
signal), Foursquare open data (doesn't exist), **Google Route Optimization** (no TRANSIT mode; its
time windows constrain arrival only; its skip reasons can't distinguish "closed" from "unreachable"),
Tokyo/Bangkok/Singapore open data (stale or geo-blocked).

## RedNote

Confirmed as a data source, strongest for food. `webapi.rednote.com`, endpoints
`/api/sns/web/v1/search/notes` and `/api/sns/web/v1/feed`.

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

## Working pipeline

Four scripts in `spikes/videos_transcribing/`, each joined by a JSON file.

```bash
python youtube_search.py Helsinki --lang en --region FI --out videos.json
python youtube_llm_pipeline.py <id> --json places.json
python resolve_places.py places.json --hours --out resolved.json
python route_day.py resolved.json --date 2026-12-06 --start 10:00 --mode walk --out day.json
```

**Search** — `search.list` + `videos.list`, one call from the 100/day search bucket. 7 usable of 10
for Helsinki; gates on ≥6 min, ≥3k views, city named in title/description.

**Extract** — `gemini-3.5-flash-lite` with a JSON schema. ~6k in / 2k out tokens, ~6s per video.

**Resolve** — 19/19 names resolved, 14/19 with usable opening hours.

**Route** — `computeRoutes` with the user's order and `optimizeWaypointOrder: false`. Returns an
encoded polyline for the map, per-leg durations, and for transit the tram/bus steps
(`2: Kauppatori -> Lasipalatsi`). Validates against real hours and daylight, e.g.
*"Uspenski: arrive 15:43, need 75 min, closes 16:00"*.

## Gotchas

**Identity**
- **`place_id` is the identity, never the name.** `Vanha Kauppahalli`/`Old Market Hall` and
  `Löyly`/`Loyly` collapse to one id. The LLM returns different names across runs even at
  temperature 0 — dedupe on the id and that stops mattering.
- **Sanity-check resolved coordinates against a city bounding box.** `Sentra` (an ASR garble)
  resolved to a business 350 km away.
- **Confidence from `userRatingCount`, not name similarity.** Zero ratings → reject. Deaccent before
  comparing names.

**Extraction**
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

**Environment**
- Corporate TLS interception needs `REQUESTS_CA_BUNDLE` / `NODE_EXTRA_CA_CERTS`.
- Rate limits are often *silent* — one API returned "0 results" while throttling. Always distinguish
  throttled from empty.
- `place_id` may be cached indefinitely; almost nothing else from Places may be.

## Prerequisites

1. **Enable Routes API** on the existing key, and restrict the key to Places + Routes + YouTube + Gemini.
2. **Confirm Places and Routes pricing** and whether caching lat/lon is permitted.
3. **Test transcript fetching from cloud egress**, not just a laptop.

## Caveats

The two findings I'd call load-bearing for your roadmap are the transit 100-day horizon and holiday hours being unfetchable 
  for future dates. Both mean a trip planned in August genuinely cannot be fully accurate for December, so the UI needs a
  re-check-nearer-the-date affordance rather than presenting an early plan as final.

## Artifacts

`spikes/videos_transcribing/` — `youtube_search.py`, `youtube_llm_pipeline.py`, `resolve_places.py`
`spikes/routes_planning/` — `route_day.py`
`spikes/xhs/` — `recommend.py` (city → restaurants), `food_spike.py`, `image_ocr.py`, `call.py`
`spikes/flights/` — earlier Google Flights price-tracking spikes
