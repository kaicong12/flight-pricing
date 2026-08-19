"""Read venue names off a RedNote post's image cards, as a fallback when the desc names none.

Runs on preview-sized images, not the originals, since Gemini bills images by resolution.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile

from call import call, endpoint, feed_body, parse_curl
from food_spike import SCHEMA, gemini_post, load_env

HERE = os.path.dirname(os.path.abspath(__file__))
GAPI = "https://generativelanguage.googleapis.com/v1beta/models"
CHEAP_MODEL = "gemini-3.5-flash-lite"

PROMPT = """You are reading the image cards of a Xiaohongshu/RedNote food post. The venue names are
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


def preview_urls(note_card, limit):
    """Preview-sized image URLs from a note_card, cheapest variant first."""
    out = []
    for img in (note_card.get("image_list") or [])[:limit]:
        url = None
        for info in img.get("info_list") or []:
            if info.get("image_scene") == "WB_PRV" and info.get("url"):
                url = info["url"]
                break
        url = url or img.get("url_pre") or img.get("url_default") or img.get("url")
        if url:
            out.append(url.replace("http://", "https://"))
    return out


def download(urls, ca=None):
    """Fetch images from the CDN. Returns [(mime, bytes)]."""
    got = []
    for u in urls:
        cmd = ["curl", "-sS", "--compressed", "--max-time", "40", "-o", "-", u]
        if ca:
            cmd += ["--cacert", ca]
        r = subprocess.run(cmd, capture_output=True)
        b = r.stdout
        if len(b) < 500:
            print(f"    image fetch failed ({len(b)}b) {u[-40:]}")
            continue
        mime = ("image/webp" if b[:4] == b"RIFF" else
                "image/png" if b[:4] == b"\x89PNG" else
                "image/avif" if b[4:12] == b"ftypavif" else "image/jpeg")
        got.append((mime, b))
        print(f"    got {len(b)/1024:>6.0f} KB  {mime}")
    return got


def ocr(images, city, title, body, key, model=CHEAP_MODEL, ca=None):
    """One multimodal call over the image cards. Returns (parsed, usage)."""
    parts = [{"text": PROMPT.format(city=city, title=title, body=body[:600])}]
    for mime, b in images:
        parts.append({"inline_data": {"mime_type": mime,
                                      "data": base64.b64encode(b).decode()}})
    req = {"contents": [{"parts": parts}],
           "generationConfig": {"responseMimeType": "application/json",
                                "responseSchema": SCHEMA, "temperature": 0}}
    d = gemini_post(model, req, key, ca)
    return (json.loads(d["candidates"][0]["content"]["parts"][0]["text"]),
            d.get("usageMetadata", {}))


def ocr_note(note_card, city, title, key, model=CHEAP_MODEL, max_images=4, ca=None):
    """Fallback entry point: OCR a note's cards. Returns (parsed_or_None, usage)."""
    urls = preview_urls(note_card, max_images)
    if not urls:
        return None, {}
    print(f"    OCR fallback: {len(urls)} of "
          f"{len(note_card.get('image_list') or [])} cards, model {model}")
    imgs = download(urls, ca)
    if not imgs:
        return None, {}
    return ocr(imgs, city, title, note_card.get("desc") or "", key, model, ca)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--note", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--city", default="Helsinki")
    ap.add_argument("--model", default=CHEAP_MODEL)
    ap.add_argument("--max-images", type=int, default=4)
    ap.add_argument("--out")
    args = ap.parse_args()

    env = load_env()
    key = env.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    # Cache note details so re-running OCR experiments costs no calls against the live session.
    cache = os.path.join(HERE, "detail_cache")
    os.makedirs(cache, exist_ok=True)
    cpath = os.path.join(cache, f"{args.note}.json")
    if os.path.exists(cpath):
        nc = json.load(open(cpath))
        print("(note detail from cache — no RedNote call)")
    else:
        ep = endpoint("feed")
        if ep:
            url, headers, cookie = ep
        else:
            url, headers, cookie, _ = parse_curl(os.path.join(HERE, "search_single_content"))
        payload = feed_body(args.note, args.token)
        status, d = call(url, headers, cookie, json.dumps(payload, ensure_ascii=False))
        if isinstance(d, str) or not d.get("success"):
            sys.exit(f"detail failed: {status} {str(d)[:150]}")
        nc = d["data"]["items"][0]["note_card"]
        json.dump(nc, open(cpath, "w"), ensure_ascii=False)

    print(f"note: {nc.get('title')}")
    print(f"desc: {len(nc.get('desc') or '')} chars, images: {len(nc.get('image_list') or [])}")
    res, usage = ocr_note(nc, args.city, nc.get("title") or "", key, args.model,
                          args.max_images, ca)
    if not res:
        sys.exit("no result — see the failure printed above")

    print(f"\n  model {args.model}  "
          f"{usage.get('promptTokenCount')}in/{usage.get('candidatesTokenCount')}out")
    print(f"  is_useful={res.get('is_useful')}  promo={res.get('is_promotional')}  "
          f"{len(res.get('places') or [])} places")
    for p in res.get("places") or []:
        loc = (f"  ({p['name_local']}, {p['name_local_confidence']})"
               if p["name_local"] != p["name_as_written"] else "")
        print(f"    + {p['category'].upper():<5} {p['name_as_written']}{loc}")
        if p.get("dish"):
            print(f"        dish: {p['dish']}")
        if p.get("quoted_price"):
            print(f"        price(unverified): {p['quoted_price']}")
        print(f"        {p['why_go'][:110]}")

    if args.out:
        json.dump({"note_id": args.note, "usage": usage, "result": res},
                  open(args.out, "w"), ensure_ascii=False, indent=1)
        print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
