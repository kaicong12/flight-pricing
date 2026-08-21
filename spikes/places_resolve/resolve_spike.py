"""THROWAWAY SPIKE: does searchText collapse our real ASR spelling variants to one place_id?

Resolves curated Tromsø names from live extractions and prints which groups merged.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
CITY = "Tromsø"
CENTRE = (69.6492047, 18.9553238)
RADIUS_M = 50000.0
# searchText's locationRestriction takes a rectangle only — a circle is a 400. (circle is
# locationBias-only, which biases rather than restricts.) So: the 50 km box around the centre.
DLAT = RADIUS_M / 1000 / 111.32
DLON = RADIUS_M / 1000 / (111.32 * math.cos(math.radians(CENTRE[0])))

FIELDS = ["places.id", "places.displayName", "places.formattedAddress", "places.location",
          "places.types", "places.primaryTypeDisplayName", "places.rating",
          "places.userRatingCount"]

GROUPS = {
    "A cable car": ["Fjellheisen", "Fjellheisen cable car", "Felheisen",
                    "Felheisen cable car", "F heis", "cable car"],
    "B hot dog": ["Raketten Bar & Pølse", "Raken Bar and Pulse", "Rocketin"],
    "C cathedral": ["Tromso Cathedral", "Tromsø Cathedral",
                    "Cathedral of Our Lady of Trumpsa"],
    "D two cafes": ["Cafe Bona", "Cafe Boner"],
    "E junk": ["bakery", "library", "sweetheart", "canola tot", "NIT"],
    "F cjk": ["Dragøy海鲜市场", "Hav寿司🍣拉面🍜餐厅"],
}

# Budget: 21 bare calls + these 8 suffixed = 29 searchText calls.
SUFFIX_PROBE = ["F heis", "cable car", "Rocketin", "Cathedral of Our Lady of Trumpsa",
                "Cafe Boner", "bakery", "canola tot", "Dragøy海鲜市场"]

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


def km(lat, lon):
    """Great-circle km from the Tromsø centre."""
    if lat is None or lon is None:
        return None
    la1, lo1 = math.radians(CENTRE[0]), math.radians(CENTRE[1])
    la2, lo2 = math.radians(lat), math.radians(lon)
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def deacc(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def search_text(query, key, ca=None):
    """searchText restricted to the Tromsø box, top result only."""
    body = {"textQuery": query, "maxResultCount": 1, "languageCode": "en",
            "locationRestriction": {"rectangle": {
                "low": {"latitude": CENTRE[0] - DLAT, "longitude": CENTRE[1] - DLON},
                "high": {"latitude": CENTRE[0] + DLAT, "longitude": CENTRE[1] + DLON}}}}
    cmd = ["curl", "-sS", "--max-time", "40"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-X", "POST", "-H", "Content-Type: application/json",
            "-H", f"X-Goog-Api-Key: {key}",
            "-H", "X-Goog-FieldMask: " + ",".join(FIELDS),
            "-d", json.dumps(body, ensure_ascii=False), SEARCH_URL]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"_error": f"non-JSON (exit {r.returncode}) {r.stdout[:120]}{r.stderr[:120]}"}
    if "error" in d:
        return {"_error": f"{d['error'].get('code')}: {d['error'].get('message', '')[:160]}"}
    hits = d.get("places") or []
    return hits[0] if hits else {}


def row(query, hit):
    """Flatten a hit into the reporting shape."""
    if "_error" in hit:
        return {"query": query, "error": hit["_error"]}
    if not hit:
        return {"query": query, "error": "ZERO RESULTS"}
    loc = hit.get("location") or {}
    types = hit.get("types") or []
    ptype = (hit.get("primaryTypeDisplayName") or {}).get("text") or ""
    return {"query": query, "place_id": hit.get("id"),
            "name": (hit.get("displayName") or {}).get("text", ""),
            "addr": hit.get("formattedAddress", ""),
            "rating": hit.get("rating"), "count": hit.get("userRatingCount") or 0,
            "ptype": ptype, "types": types,
            "km": km(loc.get("latitude"), loc.get("longitude")),
            "visitable": bool(VISITABLE.search(" ".join(types) + " " + ptype))}


def show(r):
    if "error" in r:
        print(f"  {r['query']:<34} MISS  {r['error']}")
        return
    d = f"{r['km']:.1f}km" if r["km"] is not None else "?"
    print(f"  {r['query']:<34} -> {r['name']:<34} {r['place_id']:<30} "
          f"{str(r['rating'] or '-'):>4}*({r['count']:>5})  {r['ptype']:<22} {d:>8}"
          f"{'' if r['visitable'] else '  NOT-VISITABLE'}")


def main():
    env = load_env()
    key = env.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    calls, bare, suffixed = 0, {}, {}

    for label, names in GROUPS.items():
        print(f"\n=== group {label} (bare query) ===")
        for n in names:
            r = row(n, search_text(n, key, ca))
            bare[n] = r
            calls += 1
            show(r)
            time.sleep(0.2)

    print(f"\n=== same names as '<name>, {CITY}' ({len(SUFFIX_PROBE)} probes) ===")
    for n in SUFFIX_PROBE:
        q = f"{n}, {CITY}"
        r = row(q, search_text(q, key, ca))
        suffixed[n] = r
        calls += 1
        show(r)
        time.sleep(0.2)

    print("\n=== collapse per group ===")
    for label, names in GROUPS.items():
        ids = {}
        for n in names:
            r = bare[n]
            if "place_id" in r:
                ids.setdefault(r["place_id"], []).append(n)
        misses = [n for n in names if "place_id" not in bare[n]]
        print(f"{label}: {len(ids)} distinct place_id, {len(misses)} miss")
        for pid, ns in ids.items():
            print(f"    {pid}  {bare[ns[0]]['name']}  <- {' | '.join(ns)}")
        if misses:
            print(f"    missed: {' | '.join(misses)}")

    print("\n=== bare vs suffixed ===")
    for n in SUFFIX_PROBE:
        a, b = bare[n].get("place_id"), suffixed[n].get("place_id")
        print(f"  {n:<34} bare={a or 'MISS':<30} suffixed={b or 'MISS':<30} "
              f"{'SAME' if a == b else 'DIFFERENT'}")

    print(f"\nsearchText calls: {calls}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    json.dump({"bare": bare, "suffixed": suffixed}, open(out, "w"), indent=2, ensure_ascii=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
