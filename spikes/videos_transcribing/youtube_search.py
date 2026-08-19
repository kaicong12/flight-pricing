"""Find candidate travel videos for a city via YouTube Data API v3."""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

API = "https://www.googleapis.com/youtube/v3"


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


def get(path, params, key, ca=None):
    """GET a Data API endpoint and return parsed JSON, exiting on API error."""
    q = "&".join(f"{k}={subprocess.list2cmdline([str(v)])}" for k, v in [])
    cmd = ["curl", "-sS", "--max-time", "40", "-G"]
    if ca:
        cmd += ["--cacert", ca]
    for k, v in params.items():
        cmd += ["--data-urlencode", f"{k}={v}"]
    cmd += ["--data-urlencode", f"key={key}", f"{API}/{path}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        sys.exit(f"non-JSON from {path}: {r.stdout[:200]}{r.stderr[:200]}")
    if "error" in d:
        sys.exit(f"{path} error {d['error'].get('code')}: {d['error'].get('message','')[:200]}")
    return d


def search(query, key, ca, lang=None, region=None, published_after=None, n=10):
    """search.list — costs one call from the 100/day search bucket."""
    p = {"part": "snippet", "q": query, "type": "video", "maxResults": n,
         "order": "relevance", "videoEmbeddable": "true"}
    if lang:
        p["relevanceLanguage"] = lang
    if region:
        p["regionCode"] = region
    if published_after:
        p["publishedAfter"] = published_after
    d = get("search", p, key, ca)
    return [{"id": i["id"]["videoId"], "title": i["snippet"]["title"],
             "channel": i["snippet"]["channelTitle"], "published": i["snippet"]["publishedAt"]}
            for i in d.get("items", [])]


def hydrate(ids, key, ca):
    """videos.list — duration, views, caption flag. One unit per 50 ids."""
    if not ids:
        return {}
    d = get("videos", {"part": "contentDetails,statistics,snippet", "id": ",".join(ids)}, key, ca)
    out = {}
    for it in d.get("items", []):
        cd, st, sn = it["contentDetails"], it.get("statistics", {}), it["snippet"]
        out[it["id"]] = {"duration": cd.get("duration", ""),
                         "seconds": iso_seconds(cd.get("duration", "")),
                         "captions": cd.get("caption") == "true",
                         "views": int(st.get("viewCount", 0)),
                         "description": sn.get("description", ""),
                         "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage")}
    return out


def iso_seconds(s):
    """Convert an ISO-8601 duration like PT23M25S to seconds."""
    import re
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def keep(v, meta, city):
    """Quality and city-name gate. Returns (ok, reason)."""
    if not meta:
        return False, "no metadata"
    if meta["seconds"] < 360:
        return False, f"too short ({meta['seconds']}s)"
    if meta["views"] < 3000:
        return False, f"too few views ({meta['views']})"
    blob = (v["title"] + " " + meta["description"][:600]).lower()
    if city.split(",")[0].strip().lower() not in blob:
        return False, "city not named in title or description"
    return True, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--lang", action="append", default=[],
                    help="repeatable, e.g. --lang en --lang ja")
    ap.add_argument("--region")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--per-query", type=int, default=10)
    ap.add_argument("--out")
    ap.add_argument("--ids-only", action="store_true")
    args = ap.parse_args()

    env = load_env()
    key = env.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    since = (datetime.now(timezone.utc) - timedelta(days=365 * args.years)).strftime("%Y-%m-%dT%H:%M:%SZ")
    langs = args.lang or [None]
    city = args.city

    found, calls = {}, 0
    for lang in langs:
        q = f"{city} travel guide things to do"
        hits = search(q, key, ca, lang, args.region, since, args.per_query)
        calls += 1
        for h in hits:
            found.setdefault(h["id"], {**h, "query_lang": lang or "any"})
        if not args.ids_only:
            print(f"search [{lang or 'any'}] {q!r} -> {len(hits)} results")

    meta = hydrate(list(found), key, ca)
    kept, dropped = [], []
    for vid, v in found.items():
        ok, why = keep(v, meta.get(vid), city)
        rec = {**v, **meta.get(vid, {})}
        rec.pop("description", None)
        (kept if ok else dropped).append({**rec, "reason": why})

    kept.sort(key=lambda r: -r["views"])

    if args.ids_only:
        for r in kept:
            print(r["id"])
    else:
        print(f"\n{len(kept)} kept / {len(found)} found  ({calls} search calls, "
              f"{len(found)} hydrated)\n")
        for r in kept:
            cap = "MANUAL" if r.get("captions") else "auto"
            print(f"  {r['id']}  {r['seconds']//60:>3}m {r['views']:>9,}v  {cap:<6} "
                  f"[{r['query_lang']}] {r['title'][:64]}")
        if dropped:
            print(f"\ndropped {len(dropped)}:")
            for r in dropped:
                print(f"  {r['id']}  {r['reason']:<42} {r['title'][:44]}")

    if args.out:
        json.dump({"city": city, "videos": kept, "dropped": dropped},
                  open(args.out, "w"), indent=2, ensure_ascii=False)
        if not args.ids_only:
            print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
