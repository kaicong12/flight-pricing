"""Harvest RedNote food notes for a city and extract candidate eateries via Gemini.

Emits the JSON shape resolve_places.py already consumes, so names can be checked against Places.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from call import call, endpoint, feed_body, parse_curl, search_body

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = "gemini-3.5-flash-lite"
GAPI = "https://generativelanguage.googleapis.com/v1beta/models"


def load_env():
    """Read the nearest .env walking up from this file."""
    d = HERE
    for _ in range(6):
        p = os.path.join(d, ".env")
        if os.path.exists(p):
            env = {}
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
            return env
        d2 = os.path.dirname(d)
        if d2 == d:
            break
        d = d2
    return {}


def likes(s):
    """'196' or '1.2万' to an int."""
    s = (s or "0").strip()
    m = re.fullmatch(r"([\d.]+)万", s)
    if m:
        return int(float(m.group(1)) * 10000)
    return int(re.sub(r"\D", "", s) or 0)


def search(keyword, pages=1):
    """Search notes using the signature from .env, or a captured curl. Returns note stubs."""
    ep = endpoint("search")
    if ep:
        url, headers, cookie = ep
    else:
        url, headers, cookie, _ = parse_curl(os.path.join(HERE, "search_endpoint"))
    out = []
    for page in range(1, pages + 1):
        base = search_body(keyword, page)
        status, d = call(url, headers, cookie, json.dumps(base, ensure_ascii=False))
        if isinstance(d, str) or not d.get("success"):
            print(f"  search page {page} failed: {status} {str(d)[:120]}")
            break
        for it in (d.get("data") or {}).get("items") or []:
            nc = it.get("note_card") or {}
            if not nc.get("display_title"):
                continue
            out.append({"id": it["id"], "token": it.get("xsec_token"),
                        "title": nc["display_title"], "type": nc.get("type"),
                        "likes": likes((nc.get("interact_info") or {}).get("liked_count")),
                        "author": (nc.get("user") or {}).get("nickname")})
    return out


def detail(note):
    """Fetch one note's full text, cached as a file. Returns the note_card or None."""
    cache = os.path.join(HERE, "detail_cache")
    os.makedirs(cache, exist_ok=True)
    cpath = os.path.join(cache, f"{note['id']}.json")
    if os.path.exists(cpath):
        print("    (from cache — no call)")
        return json.load(open(cpath))
    ep = endpoint("feed")
    if ep:
        url, headers, cookie = ep
    else:
        url, headers, cookie, _ = parse_curl(os.path.join(HERE, "search_single_content"))
    payload = feed_body(note["id"], note["token"])
    status, d = call(url, headers, cookie, json.dumps(payload, ensure_ascii=False))
    if isinstance(d, str) or not d.get("success"):
        print(f"  detail {note['id'][:12]} failed: {status} {str(d)[:100]}")
        return None
    items = (d.get("data") or {}).get("items") or []
    nc = (items[0].get("note_card") or None) if items else None
    if nc:
        json.dump(nc, open(cpath, "w"), ensure_ascii=False)
    return nc


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

PROMPT = """You are extracting places to eat and drink from a Xiaohongshu/RedNote post. The text is
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


RANK_SCHEMA = {
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

RANK_PROMPT = """These are titles of Xiaohongshu/RedNote posts found by searching for food in {city}.
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


def rank_titles(stubs, city, key, ca=None):
    """One cheap call to order candidates by how likely their text names venues."""
    listing = "\n".join(f"{i}: {s['title']}" for i, s in enumerate(stubs))
    body = {"contents": [{"parts": [{"text": RANK_PROMPT.format(city=city, titles=listing)}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseSchema": RANK_SCHEMA, "temperature": 0}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f)
        path = f.name
    cmd = ["curl", "-sS", "--max-time", "120"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-H", "Content-Type: application/json", "-X", "POST", "--data-binary", f"@{path}",
            f"{GAPI}/{MODEL}:generateContent?key={key}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(path)
    d = json.loads(r.stdout)
    if "error" in d:
        sys.exit(f"gemini rank {d['error'].get('code')}: {d['error'].get('message','')[:200]}")
    parsed = json.loads(d["candidates"][0]["content"]["parts"][0]["text"])
    usage = d.get("usageMetadata", {})
    by_i = {t["index"]: t for t in parsed.get("titles", [])}
    for i, s in enumerate(stubs):
        t = by_i.get(i, {})
        s["score"] = t.get("score", 0)
        s["names_a_venue"] = t.get("names_a_venue", False)
        s["promise_without_names"] = t.get("promise_without_names", False)
        s["venue_names_in_title"] = t.get("venue_names_in_title") or []
    ranked = sorted(stubs, key=lambda s: (-s["score"], not s["names_a_venue"], -s["likes"]))
    return ranked, usage


def gemini_post(model, req, key, ca=None, tries=4):
    """POST a generateContent request, retrying transient 429/500/503. Returns parsed JSON."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(req, f)
        path = f.name
    cmd = ["curl", "-sS", "--max-time", "300"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-H", "Content-Type: application/json", "-X", "POST", "--data-binary", f"@{path}",
            f"{GAPI}/{model}:generateContent?key={key}"]
    try:
        for attempt in range(tries):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if not r.stdout.strip():
                err, code = f"empty response (curl {r.returncode})", 0
            else:
                d = json.loads(r.stdout)
                if "error" not in d:
                    return d
                code = d["error"].get("code")
                err = f"{code}: {d['error'].get('message', '')[:120]}"
                if code not in (429, 500, 503):
                    sys.exit(f"gemini {err}")
            wait = 5 * (2 ** attempt)
            if attempt == tries - 1:
                sys.exit(f"gemini {err} — gave up after {tries} tries")
            print(f"    gemini {err}; retrying in {wait}s", flush=True)
            time.sleep(wait)
    finally:
        os.unlink(path)


def call_gemini(prompt, key, ca=None):
    """POST to generateContent with the schema. Returns (parsed, usage)."""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseSchema": SCHEMA, "temperature": 0}}
    d = gemini_post(MODEL, body, key, ca)
    return (json.loads(d["candidates"][0]["content"]["parts"][0]["text"]),
            d.get("usageMetadata", {}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--keyword", help="defaults to '<city> 美食'")
    ap.add_argument("--notes", type=int, default=5,
                    help="how many of the search results to fetch, in returned order")
    ap.add_argument("--out", default="food_places.json")
    ap.add_argument("--raw", default="food_raw.json")
    ap.add_argument("--no-ocr", action="store_true",
                    help="skip the image fallback for notes whose text names no venue")
    ap.add_argument("--max-images", type=int, default=7)
    ap.add_argument("--prescreen", action="store_true",
                    help="reorder candidates by title before fetching (off: use returned order)")
    args = ap.parse_args()

    env = load_env()
    gkey = env.get("GEMINI_API_KEY")
    if not gkey:
        sys.exit("GEMINI_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    kw = args.keyword or f"{args.city} 美食"
    print(f"searching {kw!r}")
    stubs = search(kw)
    if not stubs:
        sys.exit("no notes returned")
    rin = rout = 0
    if not args.prescreen:
        print(f"  {len(stubs)} notes; taking the first {args.notes} in returned order")
        ranked = stubs
    else:
        ranked, rusage = rank_titles(stubs, args.city, gkey, ca)
        rin, rout = rusage.get("promptTokenCount", 0), rusage.get("candidatesTokenCount", 0)
        print(f"  {len(stubs)} notes; prescreened titles ({rin}in/{rout}out), "
              f"taking top {args.notes} by score")
        for s_ in ranked:
            mark = "NAMES" if s_["names_a_venue"] else ("promise" if s_["promise_without_names"]
                                                        else "-")
            print(f"    score {s_['score']}  {mark:<7} {s_['likes']:>5}L  {s_['title'][:46]}"
                  + (f"  {s_['venue_names_in_title']}" if s_["venue_names_in_title"] else ""))

    picked, raw = ranked[:args.notes], []
    all_places, per_note = [], []
    tin = tout = oin = oout = 0
    for i, st in enumerate(picked, 1):
        print(f"\n[{i}/{len(picked)}] {st['likes']:>6} likes  {st['title'][:52]}")
        nc = detail(st)
        if not nc:
            continue
        desc = nc.get("desc") or ""
        tr = ((nc.get("note_translation") or {}).get("desc_trans") or "")
        raw.append({"stub": st, "desc": desc, "desc_trans": tr,
                    "tags": [t.get("name") for t in (nc.get("tag_list") or [])]})
        if len(desc) < 40:
            print(f"    desc only {len(desc)} chars — skipping extraction")
            continue
        res, usage = call_gemini(
            PROMPT.format(city=args.city, title=nc.get("title") or st["title"], body=desc),
            gkey, ca)
        tin += usage.get("promptTokenCount", 0)
        tout += usage.get("candidatesTokenCount", 0)
        flag = "" if res.get("is_useful") else "  GATED OUT"
        promo = "  [PROMOTIONAL]" if res.get("is_promotional") else ""
        print(f"    {len(desc)} chars, trans:{'y' if tr else 'n'} -> "
              f"{res.get('content_type', '?')}{flag}{promo}  "
              f"{len(res.get('places') or [])} places")

        source = "text"
        if not (res.get("places") or []) and not args.no_ocr:
            from image_ocr import ocr_note
            res2, usage2 = ocr_note(nc, args.city, nc.get("title") or st["title"], gkey,
                                    max_images=args.max_images, ca=ca)
            if res2 and (res2.get("places") or []):
                oin += usage2.get("promptTokenCount", 0)
                oout += usage2.get("candidatesTokenCount", 0)
                res, source = res2, "image"
                print(f"    image fallback -> {len(res2['places'])} places")
        for p in res.get("places") or []:
            mark = {"recommended": "+", "mixed": "~", "not_recommended": "-"}.get(p["sentiment"], "?")
            loc = (f"  ({p['name_local']}, {p['name_local_confidence']})"
                   if p["name_local"] != p["name_as_written"] else "")
            print(f"      {mark} {p['category'].upper():<5} {p['name_as_written']}{loc}")
            if p.get("dish"):
                print(f"          dish: {p['dish']}")
        per_note.append({"note": st, "result": res})
        for p in res.get("places") or []:
            all_places.append({**p, "note_id": st["id"], "note_title": st["title"],
                               "note_likes": st["likes"], "promotional": res.get("is_promotional"),
                               "extracted_from": source})

    merged = {}
    for p in all_places:
        key = re.sub(r"\s+", "", (p["name_local"] or p["name_as_written"]).lower())
        m = merged.setdefault(key, {**p, "mentions": 0, "notes": []})
        m["mentions"] += 1
        m["notes"].append(p["note_id"])

    eat = [m for m in merged.values() if m["category"] in ("eat", "drink")]
    print(f"\n{len(all_places)} extractions -> {len(merged)} distinct names, "
          f"{len(eat)} eat/drink")
    multi = sorted((m for m in merged.values() if m["mentions"] > 1),
                   key=lambda m: -m["mentions"])
    print(f"named by more than one note: {len(multi)}")
    for m in multi:
        print(f"  x{m['mentions']}  {m['name_as_written']}")
    print(f"gemini prescreen {rin}in/{rout}out   text {tin}in/{tout}out   "
          f"image-ocr {oin}in/{oout}out")
    by_src = {}
    for p in all_places:
        by_src[p["extracted_from"]] = by_src.get(p["extracted_from"], 0) + 1
    print(f"extractions by source: {by_src}")

    json.dump({"city": args.city, "keyword": kw, "notes": raw, "per_note": per_note},
              open(args.raw, "w"), ensure_ascii=False, indent=1)
    # resolve_places.py reads result.places[].name
    json.dump({"result": {"is_travel_content": True, "city": args.city,
                          "places": [{**m, "name": m["name_local"] or m["name_as_written"]}
                                     for m in merged.values()]}},
              open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"wrote {args.raw} and {args.out}")


if __name__ == "__main__":
    main()
