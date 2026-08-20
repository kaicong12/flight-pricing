"""Places out of a YouTube transcript. Ported verbatim from spikes/videos_transcribing."""

from libs.prompts.registry import GEMINI_FLASH_LITE, Prompt

SCHEMA = {
    "type": "object",
    "properties": {
        "is_travel_content": {"type": "boolean"},
        "content_type": {"type": "string"},
        "city": {"type": "string"},
        "city_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "other_cities_mentioned": {"type": "array", "items": {"type": "string"}},
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "name_confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "category": {"type": "string",
                                 "enum": ["see", "do", "eat", "drink", "buy", "sleep", "other"]},
                    "timestamp": {"type": "string"},
                    "why_go": {"type": "string"},
                    "sentiment": {"type": "string",
                                  "enum": ["recommended", "mixed", "not_recommended"]},
                    "spoken_price": {"type": "string"},
                },
                "required": ["name", "name_confidence", "category", "timestamp", "why_go",
                             "sentiment"],
            },
        },
        "rejected": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["text", "reason"],
            },
        },
    },
    "required": ["is_travel_content", "content_type", "city", "city_confidence", "places"],
}

TEMPLATE = """You are extracting places from a transcript of a travel video. It may be
speech-to-text output, so expect errors: mangled proper nouns, dropped diacritics ("Loyly" for
"Löyly"), and unreliable numbers (a EUR 3.20 fare has been transcribed as "320 euros"). People's
names, dish names and other cities all appear capitalised and are not places.

1. Set is_travel_content true ONLY if the video recommends places a traveller could visit. A sports
   competition, product review, gaming video or personal vlog that merely happens to occur somewhere
   is not travel content. If false, return an EMPTY places array. Say what it really is in
   content_type.
2. Identify the city the video is actually about. List any other cities separately; do not attribute
   their places to the main city.
3. Extract only places a traveller can visit: attractions, restaurants, cafes, bars, shops, saunas,
   neighbourhoods, museums, landmarks. Exclude chain stores and franchises unless the specific branch
   is treated as a destination; exclude airports, stations and ferry piers unless presented as a
   sight; exclude cities, countries and regions as a whole; exclude hotels unless the video is
   recommending where to stay.
4. Give each place a timestamp, a one-sentence reason to go grounded in what was said, and whether it
   was recommended.
5. Set name_confidence low if the transcription looks garbled. Do not guess a corrected spelling into
   the name field.
6. Record any spoken price verbatim in spoken_price. It will be treated as unverified.
7. In "rejected", list capitalised things you excluded and why.

Transcript:

---
{transcript}
---
"""

YOUTUBE_TRANSCRIPT = Prompt(name="youtube_transcript", version="v1", model=GEMINI_FLASH_LITE,
                            template=TEMPLATE, schema=SCHEMA)
