"""Route a user-ordered list of places for one day, and validate it against opening hours."""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import date

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places"

DURATIONS = {"see": 75, "do": 120, "eat": 75, "drink": 60, "buy": 45, "sleep": 0, "other": 60}
OUTDOOR = {"see", "do"}
MAX_INTERMEDIATES = 25


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


def post(url, body, key, mask, ca=None):
    """POST JSON with a field mask, returning parsed JSON or {'_error': ...}."""
    cmd = ["curl", "-sS", "--max-time", "60"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-X", "POST", "-H", "Content-Type: application/json",
            "-H", f"X-Goog-Api-Key: {key}", "-H", f"X-Goog-FieldMask: {mask}",
            "-d", json.dumps(body), url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
    except Exception:
        return {"_error": f"non-JSON (exit {r.returncode}) {r.stdout[:120]}"}
    if "error" in d:
        return {"_error": f"{d['error'].get('code')}: {d['error'].get('message','')[:160]}"}
    return d


def get_place(pid, key, ca=None):
    """Fetch name, location and opening hours for one place_id."""
    mask = ("id,displayName,location,regularOpeningHours.periods,"
            "regularOpeningHours.weekdayDescriptions,utcOffsetMinutes")
    cmd = ["curl", "-sS", "--max-time", "40"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-H", f"X-Goog-Api-Key: {key}", "-H", f"X-Goog-FieldMask: {mask}",
            f"{PLACES_URL}/{pid}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def window_for(place, weekday):
    """Opening window in local minutes for a weekday (0=Sunday), or None if closed/unknown.

    Google's periods[].open.day is 0=Sunday. A period with open but no close is 24h.
    """
    oh = place.get("regularOpeningHours") or {}
    periods = oh.get("periods") or []
    if not periods:
        return None
    if len(periods) == 1 and "close" not in periods[0]:
        return (0, 24 * 60)
    for p in periods:
        o = p.get("open") or {}
        if o.get("day") != weekday:
            continue
        c = p.get("close") or {}
        start = o.get("hour", 0) * 60 + o.get("minute", 0)
        end = c.get("hour", 24) * 60 + c.get("minute", 0)
        if c.get("day") != weekday:
            end = 24 * 60
        return (start, end)
    return "closed"


def sun_times(d, lat, lon, tz_min):
    """NOAA sunrise/sunset in local minutes, or (None, None) in polar night."""
    n = (date(d.year, d.month, d.day) - date(d.year, 1, 1)).days + 1
    g = (2 * math.pi / 365) * (n - 1 + 0.5)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
           - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
           - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    phi = math.radians(lat)
    cos_h = (math.cos(math.radians(90.833)) / (math.cos(phi) * math.cos(dec))
             - math.tan(phi) * math.tan(dec))
    if abs(cos_h) > 1:
        return (None, None)
    h = math.degrees(math.acos(cos_h))
    return (720 - 4 * (lon + h) - eq + tz_min, 720 - 4 * (lon - h) - eq + tz_min)


def route_walk(place_ids, key, ca=None):
    """One computeRoutes call for the whole ordered day. Returns (legs, polyline, total_s)."""
    body = {"origin": {"placeId": place_ids[0]},
            "destination": {"placeId": place_ids[-1]},
            "intermediates": [{"placeId": p} for p in place_ids[1:-1]],
            "travelMode": "WALK", "optimizeWaypointOrder": False}
    mask = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
            "routes.legs.duration,routes.legs.distanceMeters")
    d = post(ROUTES_URL, body, key, mask, ca)
    if "_error" in d:
        return None, d["_error"], None
    r = (d.get("routes") or [{}])[0]
    legs = [(int(re.sub(r"\D", "", l.get("duration", "0s")) or 0), l.get("distanceMeters", 0))
            for l in r.get("legs", [])]
    return legs, (r.get("polyline") or {}).get("encodedPolyline", ""), \
        int(re.sub(r"\D", "", r.get("duration", "0s")) or 0)


def route_transit_leg(a, b, depart_iso, key, ca=None):
    """One computeRoutes call for a single pair. Transit forbids intermediates."""
    body = {"origin": {"placeId": a}, "destination": {"placeId": b},
            "travelMode": "TRANSIT", "departureTime": depart_iso}
    mask = ("routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline,"
            "routes.legs.steps.transitDetails.transitLine.nameShort,"
            "routes.legs.steps.transitDetails.transitLine.name,"
            "routes.legs.steps.transitDetails.stopDetails.departureStop.name,"
            "routes.legs.steps.transitDetails.stopDetails.arrivalStop.name,"
            "routes.legs.steps.travelMode")
    d = post(ROUTES_URL, body, key, mask, ca)
    if "_error" in d:
        return None, d["_error"], []
    r = (d.get("routes") or [{}])[0]
    secs = int(re.sub(r"\D", "", r.get("duration", "0s")) or 0)
    steps = []
    for leg in r.get("legs", []):
        for s in leg.get("steps", []):
            td = s.get("transitDetails")
            if not td:
                continue
            line = td.get("transitLine", {})
            sd = td.get("stopDetails", {})
            steps.append(f"{line.get('nameShort') or line.get('name', '?')}: "
                         f"{sd.get('departureStop', {}).get('name', '?')} -> "
                         f"{sd.get('arrivalStop', {}).get('name', '?')}")
    return secs, (r.get("polyline") or {}).get("encodedPolyline", ""), steps


def hhmm(m):
    """Local minutes to HH:MM."""
    return f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="resolved.json from resolve_places.py")
    ap.add_argument("--ids", help="comma-separated place_ids in visiting order")
    ap.add_argument("--date", default="2026-12-06")
    ap.add_argument("--start", default="09:00")
    ap.add_argument("--mode", choices=["walk", "transit"], default="walk")
    ap.add_argument("--tz", type=int, default=120, help="local UTC offset in minutes")
    ap.add_argument("--out")
    args = ap.parse_args()

    env = load_env()
    key = env.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GOOGLE_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    if args.ids:
        ids = [i.strip() for i in args.ids.split(",") if i.strip()]
        cats = {}
    elif args.input:
        doc = json.load(open(args.input, encoding="utf-8"))
        ps = [p for p in doc["places"] if p.get("place_id")]
        ids = [p["place_id"] for p in ps]
        cats = {p["place_id"]: p.get("category", "other") for p in ps}
    else:
        sys.exit("give resolved.json or --ids")

    if len(ids) < 2:
        sys.exit("need at least two places")
    if len(ids) - 2 > MAX_INTERMEDIATES:
        sys.exit(f"{len(ids)} places exceeds the {MAX_INTERMEDIATES}-intermediate limit")

    y, m, dd = (int(x) for x in args.date.split("-"))
    weekday = (date(y, m, dd).weekday() + 1) % 7
    start_min = int(args.start[:2]) * 60 + int(args.start[3:])

    places = {pid: get_place(pid, key, ca) for pid in ids}
    first = places[ids[0]].get("location") or {}
    rise, set_ = sun_times(date(y, m, dd), first.get("latitude", 60.17),
                           first.get("longitude", 24.94), args.tz)

    print(f"{args.date} ({['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][weekday]})  "
          f"mode={args.mode}  start {args.start}")
    if rise:
        print(f"daylight {hhmm(rise)}–{hhmm(set_)}\n")

    if args.mode == "walk":
        legs, poly, total = route_walk(ids, key, ca)
        if legs is None:
            sys.exit(f"routing failed: {poly}")
        transit_steps = [[] for _ in legs]
    else:
        legs, polys, transit_steps = [], [], []
        for a, b in zip(ids, ids[1:]):
            secs, p, steps = route_transit_leg(a, b, f"{args.date}T{args.start}:00Z", key, ca)
            if secs is None:
                print(f"  transit leg failed: {p}")
                secs, p, steps = 0, "", []
            legs.append((secs, 0))
            polys.append(p)
            transit_steps.append(steps)
        poly = polys
        total = sum(s for s, _ in legs)

    t = start_min
    warnings, schedule = [], []
    for i, pid in enumerate(ids):
        pl = places[pid]
        name = (pl.get("displayName") or {}).get("text", pid[:12])
        cat = cats.get(pid, "other")
        dur = DURATIONS.get(cat, 60)
        win = window_for(pl, weekday)

        if win == "closed":
            warnings.append(f"{name}: CLOSED on this date")
        elif win is None:
            warnings.append(f"{name}: no opening hours published — unverified")
        else:
            o, c = win
            if t < o:
                warnings.append(f"{name}: arrive {hhmm(t)} but opens {hhmm(o)} — {o - t} min wait")
                t = o
            if t + dur > c:
                warnings.append(f"{name}: arrive {hhmm(t)}, need {dur} min, closes {hhmm(c)}")
        if cat in OUTDOOR and set_ and t > set_:
            warnings.append(f"{name}: outdoor stop starting {hhmm(t)}, after sunset {hhmm(set_)}")

        schedule.append({"place_id": pid, "name": name, "category": cat,
                         "start": hhmm(t), "end": hhmm(t + dur), "minutes": dur})
        print(f"  {hhmm(t)}–{hhmm(t + dur)}  {cat.upper():<5} {name}")
        t += dur

        if i < len(legs):
            secs, meters = legs[i]
            extra = f"  [{'; '.join(transit_steps[i])}]" if transit_steps[i] else ""
            dist = f" {meters}m" if meters else ""
            print(f"       ↓ {secs // 60} min{dist}{extra}")
            t += secs // 60

    print(f"\nfinish {hhmm(t)}  ·  travel {total // 60} min")
    if warnings:
        print(f"\n{len(warnings)} WARNINGS")
        for w in warnings:
            print(f"  ! {w}")

    if args.out:
        json.dump({"date": args.date, "mode": args.mode, "schedule": schedule,
                   "warnings": warnings, "polyline": poly,
                   "travel_seconds": total}, open(args.out, "w"), indent=2, ensure_ascii=False)
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
