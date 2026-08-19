"""City in, restaurant recommendations out: RedNote search -> desc extraction -> Google Places.

The whole flow a user would trigger by typing a city name.
"""

import argparse
import glob
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "videos_transcribing"))

import resolve_places as rp
from food_spike import HERE, MODEL, PROMPT, call_gemini, detail, load_env, search
from image_ocr import ocr_note

# Stopgap: the prompt's "exclude chains" rule leaks, so filter the obvious ones by name.
CHAINS = re.compile(
    r"mcdonald|kfc|burger king|subway|starbucks|genki sushi|sushi express|yang guo fu|"
    r"gong yuan|bulgogi syo|joe & the juice|jollibee|texas chicken|mos burger|"
    r"crystal jade|din tai fung|toast box|ya kun|liho|koi the|gong cha", re.I)


CJK = re.compile(r"[\u4e00-\u9fff]")


def name_check(query, official):
    """"match" / "mismatch" / "unverifiable" for a resolved name.

    tokens() in resolve_places needs words longer than two characters, so it is blind to Chinese
    names — 品记 tokenises to nothing and silently "matches" 鼎记. Compare characters when both
    sides have them. Places is asked for English names, so a Chinese query against an English
    result cannot be compared at all — that is unverifiable, not wrong.
    """
    q, o = CJK.findall(query or ""), set(CJK.findall(official or ""))
    if q and o:
        return "match" if len([c for c in q if c in o]) / len(q) >= 0.6 else "mismatch"
    if q:
        return "unverifiable"
    return "match" if (rp.tokens(query) & rp.tokens(official)) else "mismatch"


def km(a, b):
    """Great-circle distance in km between (lat, lon) pairs."""
    if not all(x is not None for x in (*a, *b)):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def harvest(city, keyword, n, gkey, ca, use_ocr=True, from_cache=False):
    """Collect extracted venues from the first n notes. Returns (places, stats)."""
    stats = {"notes": 0, "from_text": 0, "from_image": 0, "empty": 0, "negative": 0,
             "chains": 0, "far": 0, "tin": 0, "tout": 0, "oin": 0, "oout": 0}
    if from_cache:
        stubs = []
        for f in sorted(glob.glob(os.path.join(HERE, "detail_cache", "*.json")))[:n]:
            nc = json.load(open(f))
            stubs.append({"id": os.path.basename(f)[:-5], "token": nc.get("xsecToken"),
                          "title": nc.get("title") or "", "likes": 0, "cached": nc})
    else:
        stubs = search(keyword)[:n]
        if not stubs:
            return [], stats

    out = []
    for i, st in enumerate(stubs, 1):
        nc = st.get("cached") or detail(st)
        if not nc:
            continue
        stats["notes"] += 1
        desc = nc.get("desc") or ""
        title = nc.get("title") or st["title"]
        print(f"  [{i}/{len(stubs)}] {len(desc):>4} chars  {title[:46]}")

        res, source = None, "text"
        if len(desc) >= 40:
            res, usage = call_gemini(PROMPT.format(city=city, title=title, body=desc), gkey, ca)
            stats["tin"] += usage.get("promptTokenCount", 0)
            stats["tout"] += usage.get("candidatesTokenCount", 0)
        if (not res or not res.get("places")) and use_ocr:
            res2, usage2 = ocr_note(nc, city, title, gkey, ca=ca)
            if res2 and res2.get("places"):
                stats["oin"] += usage2.get("promptTokenCount", 0)
                stats["oout"] += usage2.get("candidatesTokenCount", 0)
                res, source = res2, "image"
        if not res or not res.get("places"):
            stats["empty"] += 1
            continue
        stats["from_text" if source == "text" else "from_image"] += 1
        for p in res["places"]:
            if p["category"] not in ("eat", "drink"):
                continue
            if p.get("sentiment") == "not_recommended":
                stats["negative"] += 1
                continue
            if CHAINS.search(p["name_as_written"] + " " + (p["name_local"] or "")):
                stats["chains"] += 1
                continue
            out.append({**p, "note_id": st["id"], "note_title": title,
                        "sentiment": p.get("sentiment"),
                        "note_token": st.get("token") or nc.get("xsecToken"),
                        "source": source})
    return out, stats


def resolve(places, city, gkey_places, ca, max_km=6.0, stats=None):
    """Resolve names to place_ids, drop venues far from the searched area, group and rank."""
    fields = rp.FIELDS_BASIC + rp.FIELDS_RATING
    anchor = rp.search_text(city, gkey_places, fields, ca)
    aloc = (anchor.get("location") or {}) if isinstance(anchor, dict) else {}
    centre = (aloc.get("latitude"), aloc.get("longitude"))
    if centre[0]:
        print(f"  area anchor: {(anchor.get('displayName') or {}).get('text','?')} "
              f"({centre[0]:.4f}, {centre[1]:.4f}), keeping venues within {max_km} km")
    by_id = {}
    for p in places:
        name = p["name_local"] or p["name_as_written"]
        hit = rp.search_text(f"{name}, {city}", gkey_places, fields, ca)
        if "_error" in hit or not hit:
            continue
        official = (hit.get("displayName") or {}).get("text", "")
        conf, reason = rp.judge(name, official, hit.get("userRatingCount"), hit.get("types"),
                                (hit.get("primaryTypeDisplayName") or {}).get("text"))
        verdict = name_check(name, official)
        if verdict == "mismatch":
            conf = "low"
            reason = f"resolved to {official!r}, which is not {name!r} — likely the wrong venue"
        elif verdict == "unverifiable" and conf == "high":
            conf, reason = "medium", "English result for a Chinese name — identity unconfirmed"
        loc = hit.get("location") or {}
        dist = km(centre, (loc.get("latitude"), loc.get("longitude"))) if centre[0] else None
        if dist is not None and dist > max_km:
            if stats is not None:
                stats["far"] += 1
            continue
        pid = hit.get("id")
        rec = by_id.setdefault(pid, {
            "km": round(dist, 1) if dist is not None else None,
            "place_id": pid, "name": official, "address": hit.get("formattedAddress"),
            "rating": hit.get("rating"), "rating_count": hit.get("userRatingCount"),
            "confidence": conf, "confidence_reason": reason, "notes": [], "dishes": [],
            "why": [], "prices": [], "sources": set(), "sentiments": []})
        if p["note_id"] not in [n["id"] for n in rec["notes"]]:
            rec["notes"].append({"id": p["note_id"], "title": p["note_title"],
                                 "token": p["note_token"]})
        for key, field in (("dishes", "dish"), ("why", "why_go"), ("prices", "quoted_price")):
            v = p.get(field)
            if v and v not in rec[key]:
                rec[key].append(v)
        rec["sources"].add(p["source"])
        if p.get("sentiment"):
            rec["sentiments"].append(p["sentiment"])
    wrong = [r for r in by_id.values() if "likely the wrong venue" in r["confidence_reason"]]
    for r in wrong:
        print(f"  dropped: {r['name']} — {r['confidence_reason']}")
        del by_id[r["place_id"]]
    ranked = sorted(by_id.values(),
                    key=lambda r: (-len(r["notes"]), -(r["rating_count"] or 0)))
    return ranked


def show(ranked, city, top):
    """Print the list a user would see."""
    print(f"\n{'=' * 78}\nRestaurants people recommend in {city}, from RedNote\n{'=' * 78}")
    for i, r in enumerate(ranked[:top], 1):
        star = f"google {r['rating']}* ({r['rating_count']})" if r["rating"] else "google: unrated"
        mixed = "  ·  RedNote is lukewarm on this one" if "mixed" in r["sentiments"] else ""
        flag = ("  [" + r["confidence"].upper() + ": " + r["confidence_reason"] + "]"
                if r["confidence"] != "high" else "")
        agree = f"  ·  named by {len(r['notes'])} posts" if len(r["notes"]) > 1 else ""
        near = f"  ·  {r['km']} km" if r.get("km") is not None else ""
        print(f"\n{i}. {r['name']}   {star}{agree}{near}{mixed}{flag}")
        if r["dishes"]:
            print(f"   try: {', '.join(r['dishes'][:3])}")
        if r["why"]:
            print(f"   {r['why'][0][:150]}")
        if r["prices"]:
            print(f"   price mentioned (unverified): {r['prices'][0][:70]}")
        print(f"   {(r['address'] or '')[:70]}")
        for n in r["notes"][:2]:
            link = f"https://www.rednote.com/explore/{n['id']}"
            if n["token"]:
                link += f"?xsec_token={n['token']}&xsec_source=pc_search"
            print(f"   source: {n['title'][:44]}")
            print(f"           {link}")
    print(f"\nCheck opening hours and whether you need to book — we don't verify those.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--keyword", help="defaults to '<city> 美食'")
    ap.add_argument("--notes", type=int, default=10)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--no-ocr", action="store_true")
    ap.add_argument("--from-cache", action="store_true",
                    help="use already-fetched notes in detail_cache, no RedNote calls")
    ap.add_argument("--out")
    args = ap.parse_args()

    env = load_env()
    gkey = env.get("GEMINI_API_KEY")
    pkey = env.get("GOOGLE_API_KEY")
    if not gkey or not pkey:
        sys.exit("need GEMINI_API_KEY and GOOGLE_API_KEY in .env")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    kw = args.keyword or f"{args.city} 美食"
    print(f"searching RedNote for {kw!r}")
    places, stats = harvest(args.city, kw, args.notes, gkey, ca,
                            use_ocr=not args.no_ocr, from_cache=args.from_cache)
    if not places:
        sys.exit("no venues extracted")
    print(f"\n{len(places)} mentions kept from {stats['notes']} notes "
          f"(text {stats['from_text']}, images {stats['from_image']}, empty {stats['empty']}; "
          f"dropped {stats['negative']} negative, {stats['chains']} chains)")

    ranked = resolve(places, args.city, pkey, ca, stats=stats)
    print(f"{len(ranked)} distinct venues resolved ({stats['far']} dropped as too far)")
    show(ranked, args.city, args.top)
    print(f"\ngemini: text {stats['tin']}in/{stats['tout']}out, "
          f"images {stats['oin']}in/{stats['oout']}out  ({MODEL})")

    if args.out:
        for r in ranked:
            r["sources"] = sorted(r["sources"])
        json.dump({"city": args.city, "keyword": kw, "venues": ranked},
                  open(args.out, "w"), ensure_ascii=False, indent=1)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
