"""Eateries out of a RedNote post's text body. Ported verbatim from spikes/xhs/food_spike.py."""

from libs.prompts.registry import Prompt

SCHEMA = {
    "type": "object",
    "properties": {
        "is_useful": {"type": "boolean"},
        "content_type": {"type": "string"},
        "is_promotional": {"type": "boolean"},
        "city": {"type": "string"},
        "city_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name_as_written": {"type": "string"},
                    "name_local": {"type": "string"},
                    "name_local_confidence": {"type": "string",
                                              "enum": ["high", "medium", "low", "unknown"]},
                    "category": {"type": "string",
                                 "enum": ["eat", "drink", "see", "do", "buy", "other"]},
                    "dish": {"type": "string"},
                    "why_go": {"type": "string"},
                    "sentiment": {"type": "string",
                                  "enum": ["recommended", "mixed", "not_recommended"]},
                    "quoted_price": {"type": "string"},
                    "needs_booking_claim": {"type": "boolean"},
                },
                "required": ["name_as_written", "name_local", "name_local_confidence", "category",
                             "why_go", "sentiment"],
            },
        },
        "rejected": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"text": {"type": "string"}, "reason": {"type": "string"}},
                      "required": ["text", "reason"]},
        },
    },
    "required": ["is_useful", "content_type", "is_promotional", "city", "city_confidence", "places"],
}

TEMPLATE = """You are extracting places to eat and drink from a Xiaohongshu/RedNote post. The text is
typed, not speech-to-text, so spelling is reliable, but it is written for a Chinese audience and is
full of hashtags, emoji and marketing language.

1. Set is_useful true only if the post recommends specific named places a traveller could go to. A
   post that is only scenery photos, a visa/packing guide, a complaint, or pure trip narration with
   no named venues is not useful — return an empty places array and say what it is in content_type.
2. Set is_promotional true if the post reads as sponsored or affiliate content (agency tags, booking
   links, discount codes, "合作", tour-operator branding).
3. Extract only specific, visitable venues. EXCLUDE: dish names, supermarket own-brands, chains and
   franchises unless that branch is itself the destination, airports and stations, whole cities,
   districts or countries, and generic categories ("a salmon soup place").
4. name_as_written: exactly as the post writes it, Chinese included. name_local: the name as it would
   appear on the venue's own sign in the local language, if you are confident of it — this is a
   translation of a known exonym, NOT a guess. If you do not know it, repeat name_as_written and set
   name_local_confidence to "unknown". Never invent a plausible-looking foreign name.
5. dish: the specific thing recommended there, if named. quoted_price: any price stated, verbatim.
   Prices and any claim about needing a booking are UNVERIFIED — record them, do not assess them.
6. needs_booking_claim: true only if the post itself claims a reservation is needed.
7. why_go: one sentence, in English, grounded in what the post actually says.
8. In "rejected", list named things you excluded and why.

City the search was about: {city}

Post title: {title}

Post body:
---
{body}
---
"""

REDNOTE_TEXT = Prompt(name="rednote_text", version="v1", template=TEMPLATE, schema=SCHEMA)
