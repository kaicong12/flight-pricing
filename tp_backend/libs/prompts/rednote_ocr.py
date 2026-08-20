"""Reading venue names off a RedNote post's image cards, when the text body named none.

Same schema as rednote_text so both extraction paths land in the same columns; ~10x the tokens, so
this runs only as a fallback.
"""

from libs.prompts.rednote_text import SCHEMA
from libs.prompts.registry import GEMINI_FLASH_LITE, Prompt

TEMPLATE = """You are reading the image cards of a Xiaohongshu/RedNote food post. The venue names are
printed on the images themselves — the post's text body did not name them.

Read the names off the cards. Rules:

1. Extract only specific, named, visitable venues. A dish name, a price, a hashtag, the city name or
   a slogan is not a venue.
2. Transcribe names EXACTLY as printed, including Latin-script names. Do not translate, correct or
   complete a name you can only partly read — if it is cut off or illegible, skip it.
3. name_as_written: as printed on the card. name_local: the name as it would appear on the venue's
   own sign, only if you are confident; otherwise repeat name_as_written and set
   name_local_confidence to "unknown". Never invent a plausible foreign name.
4. Prices and any claim that booking is needed are UNVERIFIED. Record them verbatim; do not judge.
5. why_go: one sentence, WRITTEN IN ENGLISH, grounded only in what the cards actually say. The cards
   are in Chinese; translate their point into English rather than copying the Chinese text. If a card
   says nothing beyond the name, say so plainly rather than inventing praise.
6. Set is_useful false and return an empty places array if the cards name no venues.

City the search was about: {city}

Post title: {title}

Post text body (context only — it named no venues, that is why you are reading the images):
---
{body}
---
"""

REDNOTE_OCR = Prompt(name="rednote_ocr", version="v1", model=GEMINI_FLASH_LITE,
                     template=TEMPLATE, schema=SCHEMA)
