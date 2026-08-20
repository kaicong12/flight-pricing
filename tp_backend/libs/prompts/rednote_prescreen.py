"""Scoring RedNote titles before paying to read the posts. Off by default in the spike, which takes
search results in the API's own relevance order instead."""

from libs.prompts.registry import Prompt

SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "names_a_venue": {"type": "boolean"},
                    "venue_names_in_title": {"type": "array", "items": {"type": "string"}},
                    "promise_without_names": {"type": "boolean"},
                    "score": {"type": "integer"},
                },
                "required": ["index", "names_a_venue", "promise_without_names", "score"],
            },
        },
    },
    "required": ["titles"],
}

TEMPLATE = """These are titles of Xiaohongshu/RedNote posts found by searching for food in {city}.
Judge each title only — you cannot see the posts.

For each, decide:
- names_a_venue: does the title name a specific eatery (a restaurant, cafe, bakery, bar, market hall
  or stall)? A dish, a city, a district, a country, a count ("4 places"), or a generic phrase
  ("must-eat") is NOT a venue name.
- venue_names_in_title: the venue names you can see, verbatim.
- promise_without_names: true if it promises a list or a count but names nothing — those posts usually
  keep their content in the images, which is expensive to read.
- score 1-5: how likely this post's TEXT names specific eateries a traveller could go to. Titles that
  already name a venue score high. Bare listicle promises score low. Off-topic posts (scenery,
  visas, complaints, shopping) score 1.

Titles:
{titles}
"""

REDNOTE_PRESCREEN = Prompt(name="rednote_prescreen", version="v1", template=TEMPLATE, schema=SCHEMA)
