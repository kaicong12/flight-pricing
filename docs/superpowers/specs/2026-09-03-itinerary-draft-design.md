# Itinerary draft — design

**One Gemini call, no tools, no agent loop.** The candidate set is already in Postgres and the
validator already exists, so the model's only job is to propose an arrangement. Everything that
could be wrong about that arrangement is checked afterwards by code we already ship.

## Why not an agent

An agent loop is worth its cost when the model has to *find* something it cannot be handed. Nothing
in planning fits that:

| What an agent would fetch | Why it does not need to |
|---|---|
| Candidate places | `GET /trips/{id}/shortlist` already ranks the whole city. Closed set, ~40–60 rows. |
| Opening hours | `plan_day` checks them against the real clock. A model reading `periods` JSON is strictly worse. |
| Travel times | `POST /days/{n}/route` gets them from `computeRoutes`, per leg. |
| Daylight | Computed locally, exactly. |
| "Is this day too packed?" | That is `closes_before_done` / `after_sunset` / `no_route`, already emitted with structured codes. |

A propose → route → read-warnings → reorder → route loop also spends one `computeRoutes` per
iteration per day, and open item 3 says day routes are not cached: three iterations over four days
is twelve paid uncached calls per draft. The product thesis already names who the loop is —
**the user**. They drag, we re-route, we warn.

Where an agent would genuinely earn its keep is *discovery*, not planning: a thin city where the
shortlist is too short and something has to go looking (Wikivoyage, more search terms). That is a
new `tp_ingestions` task kind, not a step in the planning path.

## Tension with the thesis, stated plainly

CLAUDE.md says **we do not optimise the order**. A model that assigns days and orders them is
adjacent to doing exactly that. The line this design draws:

- The draft only fills days that are **currently empty**. It never touches a day with items in it.
- It writes through the same path as `PUT /itinerary`, so the result is an ordinary user itinerary
  from the first moment — draggable, re-routable, not a special "AI plan" mode.
- No re-draft, no "improve this day". A day the user has touched is theirs.

So it is a starting arrangement, not an optimiser. The alternative — LLM picks *which* places suit
the traveller and geometry (a nearest-neighbour walk over lat/lon) picks the order — keeps the
thesis cleaner and is a decision worth confirming before implementation.

## Flow

```
POST /trips/{id}/itinerary/draft
  → shortlist query (existing)  → context string
  → limits.gemini().take()      → libs.gemini.generate(ITINERARY_DRAFT, ...)
  → sanitise(reply, allowed, empty_days, cap)   ← pure, the only new logic worth testing
  → _write_days(...)            ← extracted from put_itinerary, one dense renumbering
  → ItineraryOut                ← same schema the PUT returns
```

The client then routes each day exactly as it does today. The draft endpoint spends no Places or
Routes quota at all.

## What the model is handed

Assembled in Python, one query, no tool calls:

- Trip: city name, country, dates, `arrive_time`, `depart_time`, and `extra_details` — the one
  sentence about the traveller, which is the actual reason to use an LLM here rather than k-means
  over lat/lon.
- The empty day indexes, with their dates and weekday names.
- Shortlist rows: `place_id`, `name`, `category`, `primary_type`, `mention_count`, `why_go`,
  `lat`, `lon`. Dismissals and already-placed venues are excluded by the existing query.

~2.5k tokens in for 40 places. Durations are **not** asked for — `duration_for(category)` already
answers that, so it is one fewer thing to validate.

## Schema

```json
{"days": [{"day_index": 0, "place_ids": ["ChIJ...", "ChIJ..."]}]}
```

Nothing else. A per-day rationale string has nowhere to be displayed without a migration, so it is
out.

## sanitise() — the trust boundary

The model returns opaque `ChIJ…` strings, which is precisely the kind of token a model corrupts.
Pure function, no DB, no FastAPI:

1. Drop any `place_id` not in the set we sent.
2. Drop any `day_index` not in the requested empty days.
3. Keep the first occurrence of a duplicated place — `uq_itinerary_trip_place` makes a second one an
   integrity error, not a bad plan.
4. Truncate any day past `settings().max_stops_per_day`.

A sanitised-to-nothing reply returns the unchanged itinerary rather than a 500.

## Files

| | |
|---|---|
| `libs/prompts/itinerary_draft.py` | New prompt + `responseSchema`, `version="v1"`. |
| `tp_api/draft.py` | New. Pure `render_context()` and `sanitise()`. No DB, no FastAPI. |
| `tp_api/plan_routes.py` | The ~30-line endpoint; extract `_write_days()` out of `put_itinerary`. |
| `tp_api/deps.py` | `DraftLLM = Callable[[str], dict]` so tests override it, as `route_compute` is. |
| `tests/test_itinerary_draft.py` | `sanitise` cases directly + one endpoint test through TestClient. |
| `tp_client/src/app/api/trips/[tripId]/draft/route.ts` | Proxy, mirroring the itinerary proxy. |
| `tp_client/src/components/plan/plan-header.tsx` | One button, shown only while the itinerary is empty. |

## Errors

`limits.gemini().take()` raises `Throttled` past its 60s inline wait and `TaskError(QUOTA)` when the
daily budget is spent — both are worker vocabulary and would surface as a 500. The endpoint maps
them to 503 and 429. Gemini's throttle is shared with the worker on purpose: one account, one budget.

## Cost

One Gemini call per draft, on the shared 15/min + 1000/day budget, behind a 4s ± 1s gap. Worst case
the user waits ~5s plus generation. No new tables, no new task kinds, no queue work.

## Testing

`sanitise` is where a bug ships silently, so it is tested directly: hallucinated id dropped,
duplicate place kept once, out-of-range day dropped, over-cap day truncated, empty result is a
no-op. The endpoint gets one test with `DraftLLM` overridden — no live call, matching the existing
`hours_lookup` / `route_compute` pattern.

## Deliberately skipped

- **Re-draft / "improve this day".** Add when a real draft is disappointing in a way the user cannot
  fix by dragging.
- **Two-stage reduce-then-order** for cities with 200+ places. Add when one city overflows the
  context; still two calls, still not an agent.
- **Caching the draft.** It is one cheap call and the result is written to `itinerary_items`, which
  is the cache.
