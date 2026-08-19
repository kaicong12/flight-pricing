"""Replay a captured RedNote curl with a swapped JSON body, to test what the x-s signature covers.

Calls hit a live logged-in session, so every request goes through a throttle whose state persists
in .ratelimit.json — the budget survives across separate runs of this script.
"""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import uuid

MIN_GAP = 10.0          # seconds between calls
JITTER = 5.0            # random extra, so the spacing isn't machine-regular
MAX_PER_HOUR = 60
MAX_PER_DAY = 120
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".ratelimit.json")


def throttle(dry=False):
    """Block until the next call is allowed; abort if the hourly or daily budget is spent."""
    now = time.time()
    hist = []
    if os.path.exists(STATE):
        try:
            hist = json.load(open(STATE)).get("calls", [])
        except Exception:
            hist = []
    hour = [t for t in hist if now - t < 3600]
    day = [t for t in hist if now - t < 86400]
    if len(day) >= MAX_PER_DAY:
        sys.exit(f"daily cap reached ({MAX_PER_DAY}); wait or edit MAX_PER_DAY")
    while len(hour) >= MAX_PER_HOUR:
        # Wait for a slot rather than exiting, so a long-running watcher survives the cap.
        wait = max(1, int(3601 - (now - min(hour))))
        print(f"[throttle] hourly cap ({MAX_PER_HOUR}) reached; waiting {wait}s for a slot",
              flush=True)
        if dry:
            break
        time.sleep(wait)
        now = time.time()
        hour = [t for t in hour if now - t < 3600]
    if hist:
        gap = now - max(hist)
        need = MIN_GAP + random.uniform(0, JITTER)
        if gap < need:
            sleep = need - gap
            print(f"[throttle] sleeping {sleep:.0f}s "
                  f"({len(hour)}/{MAX_PER_HOUR} this hour, {len(day)}/{MAX_PER_DAY} today)")
            if not dry:
                time.sleep(sleep)
    day.append(time.time())
    json.dump({"calls": day}, open(STATE, "w"))


def load_env():
    """Read the nearest .env walking up from this file."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        f = os.path.join(d, ".env")
        if os.path.exists(f):
            env = {}
            for line in open(f, encoding="utf-8"):
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


def env_cookie():
    """XHS_COOKIE from the nearest .env — the part that expires and gets rotated."""
    return load_env().get("XHS_COOKIE", "")


UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

ENDPOINTS = {
    "search": ("https://webapi.rednote.com/api/sns/web/v1/search/notes", "XHS_SEARCH_"),
    "feed": ("https://webapi.rednote.com/api/sns/web/v1/feed", "XHS_FEED_"),
}


def endpoint(kind):
    """Build (url, headers, cookie) for an endpoint from .env signature vars.

    Returns None if the vars are absent, so callers can fall back to a captured curl file.
    """
    url, prefix = ENDPOINTS[kind]
    env = load_env()
    xs, xt = env.get(prefix + "XS"), env.get(prefix + "XT")
    common, rap = env.get(prefix + "XS_COMMON"), env.get(prefix + "XRAP")
    if not (xs and xt and common):
        return None
    headers = [
        "accept: application/json, text/plain, */*",
        "accept-language: en-US,en;q=0.9,zh-CN;q=0.8",
        "content-type: application/json;charset=UTF-8",
        "origin: https://www.rednote.com",
        "referer: https://www.rednote.com/",
        "sec-fetch-dest: empty",
        "sec-fetch-mode: cors",
        "sec-fetch-site: same-site",
        f"user-agent: {UA}",
        f"x-s: {xs}",
        f"x-t: {xt}",
        f"x-s-common: {common}",
        "xy-common-params: mlanguage=en_us&appKey=rednote",
    ]
    if rap:
        headers.append(f"x-rap-param: {rap}")
    return url, headers, env.get("XHS_COOKIE", "")


def search_body(keyword, page=1, page_size=20):
    """Request body for search/notes."""
    return {"keyword": keyword, "page": page, "page_size": page_size,
            "search_id": uuid.uuid4().hex[:21], "sort": "general", "note_type": 0,
            "ext_flags": [], "geo": "", "image_formats": ["jpg", "webp", "avif"]}


def feed_body(note_id, token):
    """Request body for feed (one note's full content)."""
    return {"source_note_id": note_id, "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"}, "xsec_source": "pc_feed",
            "xsec_token": token, "need_translation": 1}


def parse_curl(path):
    """Pull url, -H headers and cookie out of a saved curl command.

    The signature headers never expire but the session cookie does, so XHS_COOKIE from .env wins
    over the one baked into the capture — rotating the session means editing only that variable.
    """
    txt = open(path, encoding="utf-8").read()
    url = re.search(r"--url\s+'([^']+)'", txt).group(1)
    headers = re.findall(r"-H\s+'([^']+)'", txt)
    m = re.search(r"-b\s+'([^']+)'", txt)
    cookie = env_cookie() or (m.group(1) if m else "")
    m = re.search(r"--data-raw\s+'(.*?)'\s*$", txt, re.S)
    body = m.group(1) if m else ""
    return url, headers, cookie, body


def call(url, headers, cookie, body):
    """POST the body with the captured headers, after the throttle. Returns (status, parsed)."""
    throttle()
    cmd = ["curl", "-sS", "--compressed", "--max-time", "40",
           "-w", "\n__S__%{http_code}", "--url", url, "-b", cookie]
    for h in headers:
        cmd += ["-H", h]
    cmd += ["--data-raw", body]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = r.stdout
    m = re.search(r"\n__S__(\d+)$", out)
    status, out = (m.group(1), out[:m.start()]) if m else ("?", out)
    try:
        return status, json.loads(out)
    except Exception:
        return status, out[:300]


def summarise(status, d):
    """One line of verdict plus item titles when the call succeeded."""
    if isinstance(d, str):
        return f"status={status} non-JSON: {d[:160]}"
    head = (f"status={status} success={d.get('success')} code={d.get('code')} "
            f"msg={d.get('msg', '')[:40]}")
    items = (d.get("data") or {}).get("items") or []
    if items:
        head += f" items={len(items)}"
        titles = []
        for it in items[:4]:
            nc = it.get("note_card") or {}
            titles.append((nc.get("display_title") or nc.get("title") or "?")[:34])
        head += " | " + " / ".join(titles)
    return head


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("curlfile")
    ap.add_argument("--keyword")
    ap.add_argument("--page", type=int)
    ap.add_argument("--note")
    ap.add_argument("--token")
    ap.add_argument("--raw", help="replace the whole JSON body")
    ap.add_argument("--out")
    ap.add_argument("--env-cookie", action="store_true",
                    help="swap in XHS_COOKIE from .env, keeping the captured signature headers")
    args = ap.parse_args()

    url, headers, cookie, body = parse_curl(args.curlfile)
    if args.env_cookie:
        fresh = env_cookie()
        if not fresh:
            sys.exit("XHS_COOKIE not found in .env")
        print(f"using .env cookie ({len(fresh.split(';'))} pairs) with the captured signature")
        cookie = fresh
    payload = json.loads(body) if body else {}
    if args.raw:
        payload = json.loads(args.raw)
    if args.keyword:
        payload["keyword"] = args.keyword
    if args.page:
        payload["page"] = args.page
    if args.note:
        payload["source_note_id"] = args.note
    if args.token:
        payload["xsec_token"] = args.token

    status, d = call(url, headers, cookie, json.dumps(payload, ensure_ascii=False))
    print(summarise(status, d))
    if args.out and not isinstance(d, str):
        json.dump(d, open(args.out, "w"), ensure_ascii=False, indent=1)
        print(f"wrote {args.out}")
    return 0 if not isinstance(d, str) and d.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
