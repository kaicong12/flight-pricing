"""Drafting a first itinerary. The model owns the clock; plan_day judges it afterwards.

Places are numbered rather than named by place_id, and km-from-centre is precomputed, so the model
never copies an opaque string or does trigonometry.
"""

from libs.prompts.registry import Prompt

SCHEMA = {
    "type": "object",
    "properties": {
        "days": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "day": {"type": "integer"},
                    "picks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "index": {"type": "integer"},
                                "start_min": {"type": "integer"},
                                "duration_min": {"type": "integer"},
                            },
                            "required": ["index", "start_min", "duration_min"],
                        },
                    },
                },
                "required": ["day", "picks"],
            },
        }
    },
    "required": ["days"],
}

TEMPLATE = """Draft a first-pass itinerary. The traveller will rearrange it themselves afterwards,
so a reasonable starting arrangement beats a clever one.

{city}
The traveller says: {traveller}

{days_line}

Fill only these days: {open_days}. The others are already arranged and are not yours to touch.
At most {cap} places per day. Use each place at most once across the whole trip.

You decide the clock. For every place give:
  start_min      when the traveller arrives, in minutes after local midnight (09:30 is 570)
  duration_min   how long they stay, at least 30

Both must be multiples of 30. Every block must fit inside its day's usable range above:
start_min is at or after the range's first minute, and start_min + duration_min is at or before its
last. A day's blocks must not overlap, and you must leave a gap between them for getting across
town — 10 to 20 minutes on foot in the centre, and an hour each way for anything listed far out.

"km" is straight-line distance from the city centre. Past about 5km a place is an excursion that
eats most of a day. Things that need darkness belong after sunset; things that need daylight do not.

Places, by index:
{places}

Return the days you filled and the places you chose, each with its own times. Choose for this
traveller rather than for coverage — leaving a famous place out is correct if they would not enjoy
it. Never invent an index.
{feedback}"""

ITINERARY_DRAFT = Prompt(name="itinerary_draft", version="v1", template=TEMPLATE, schema=SCHEMA)
