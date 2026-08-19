"""Resolve extracted place names to Google Place IDs, which are the real identity key."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

FIELDS_BASIC = ["places.id", "places.displayName", "places.formattedAddress",
                "places.location", "places.types", "places.primaryTypeDisplayName"]
FIELDS_RATING = ["places.rating", "places.userRatingCount"]
FIELDS_HOURS = ["places.regularOpeningHours", "places.utcOffsetMinutes"]

GENERIC = {"the", "a", "an", "cafe", "café", "restaurant", "bar", "museum", "church", "cathedral",
           "hall", "market", "park", "hotel", "sauna", "shop", "store", "art", "old", "new",
           "helsinki", "tokyo", "bangkok", "ravintola", "of", "and", "&"}

VISITABLE = re.compile(
    r"restaurant|cafe|bar|museum|church|temple|mosque|synagogue|park|store|shop|market|"
    r"tourist|attraction|landmark|gallery|spa|sauna|hotel|lodging|bakery|food|point_of_interest|"
    r"establishment|art|library|zoo|aquarium|stadium|theater|theatre|night_club", re.I)


def load_env():
    """Read the nearest .env walking up from this file."""
    d = os.path.abspath(os.path.dirname(__file__))
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


def tokens(s):
    """Deaccented content tokens, so Loyly and Löyly compare equal."""
    flat = "".join(c for c in unicodedata.normalize("NFKD", s or "")
                   if not unicodedata.combining(c))
    return {w for w in re.split(r"\W+", flat.lower()) if len(w) > 2 and w not in GENERIC}


def judge(query_name, official_name, rating_count, types, primary_type):
    """Score a resolution as high/medium/low. Rating count is the strongest signal."""
    nrat = rating_count or 0
    visitable = bool(VISITABLE.search(" ".join(types or []) + " " + (primary_type or "")))
    if nrat >= 100 and visitable:
        return "high", ""
    if nrat == 0:
        return "low", "no ratings — likely not a destination"
    if not visitable:
        return "low", f"type not visitable ({primary_type or (types or ['?'])[0]})"
    if nrat < 20:
        return "low", f"only {nrat} ratings"
    if not (tokens(query_name) & tokens(official_name)):
        return "medium", "name shares no token with the query"
    return "medium", f"{nrat} ratings"


def search_text(query, key, fields, ca=None):
    """Places API (New) searchText, top result only."""
    body = {"textQuery": query, "maxResultCount": 1, "languageCode": "en"}
    cmd = ["curl", "-sS", "--max-time", "40"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-X", "POST", "-H", "Content-Type: application/json",
            "-H", f"X-Goog-Api-Key: {key}",
            "-H", "X-Goog-FieldMask: " + ",".join(fields),
            "-d", json.dumps(body), SEARCH_URL]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"_error": f"non-JSON (exit {r.returncode})"}
    if "error" in d:
        return {"_error": f"{d['error'].get('code')}: {d['error'].get('message','')[:140]}"}
    hits = d.get("places") or []
    return hits[0] if hits else {}


def collect(args):
    """Build the list of names to resolve from --names, a JSON file, or stdin."""
    if args.names:
        return args.city, [{"name": n.strip()} for n in args.names.split(",") if n.strip()]
    if not args.input:
        sys.exit("give a JSON file, - for stdin, or --names")
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    doc = json.loads(raw)
    res = doc.get("result", doc)
    if not res.get("is_travel_content", True):
        print(f"gated out as non-travel content ({res.get('content_type','?')}) — nothing to resolve")
        sys.exit(0)
    return args.city or res.get("city", ""), res.get("places", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("--names")
    ap.add_argument("--city", default="")
    ap.add_argument("--hours", action="store_true", help="pricier field-mask tier")
    ap.add_argument("--out")
    args = ap.parse_args()

    env = load_env()
    key = env.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    city, items = collect(args)
    fields = FIELDS_BASIC + FIELDS_RATING + (FIELDS_HOURS if args.hours else [])
    print(f"resolving {len(items)} names in {city or '(no city)'}\n")

    resolved, by_id, failures, low = [], {}, 0, 0
    for it in items:
        name = it["name"]
        hit = search_text(f"{name}, {city}" if city else name, key, fields, ca)
        time.sleep(0.15)

        if "_error" in hit or not hit:
            print(f"  MISS {name:<26} {hit.get('_error', 'no result')}")
            failures += 1
            resolved.append({**it, "place_id": None})
            continue

        official = (hit.get("displayName") or {}).get("text", "")
        nrat = hit.get("userRatingCount")
        conf, reason = judge(name, official, nrat, hit.get("types"),
                             (hit.get("primaryTypeDisplayName") or {}).get("text"))
        if conf == "low":
            low += 1
        loc = hit.get("location") or {}
        hrs = ("  hours:yes" if hit.get("regularOpeningHours") else "  hours:NONE") if args.hours else ""
        star = f"{hit.get('rating')}*({nrat})" if hit.get("rating") else "no rating"
        flag = f"  LOW: {reason}" if conf == "low" else ""
        print(f"  OK   {name:<26} -> {official:<32} {star:<13}{hrs}{flag}")

        by_id.setdefault(hit.get("id"), []).append(name)
        resolved.append({**it, "place_id": hit.get("id"), "official_name": official,
                         "address": hit.get("formattedAddress"),
                         "lat": loc.get("latitude"), "lon": loc.get("longitude"),
                         "rating": hit.get("rating"), "rating_count": nrat,
                         "has_hours": bool(hit.get("regularOpeningHours")) if args.hours else None,
                         "confidence": conf, "confidence_reason": reason})

    ok = len(items) - failures
    print(f"\nresolved {ok}/{len(items)}  distinct ids {len(by_id)}  low confidence {low}")
    for pid, names in ((k, v) for k, v in by_id.items() if len(v) > 1):
        print(f"  merged: {pid} <- {' | '.join(names)}")

    if args.out:
        json.dump({"city": city, "places": resolved}, open(args.out, "w"),
                  indent=2, ensure_ascii=False)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
