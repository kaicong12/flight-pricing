"""Turn a YouTube transcript into structured place records via Gemini."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

MODEL_DEFAULT = "gemini-3.5-flash-lite"
API = "https://generativelanguage.googleapis.com/v1beta/models"


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


def video_id(s):
    """Accept a bare id, watch URL, youtu.be or shorts link."""
    if re.fullmatch(r"[\w-]{11}", s):
        return s
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([\w-]{11})", s)
    if not m:
        sys.exit(f"no video id in {s!r}")
    return m.group(1)


def fetch_transcript(vid):
    """Return (segments, is_auto_generated). Segments are (start_seconds, text)."""
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    generated = None
    try:
        for t in api.list(vid):
            if t.language_code.startswith("en"):
                generated = t.is_generated
                break
    except Exception:
        pass
    try:
        segs = list(api.fetch(vid))
    except AttributeError:
        segs = YouTubeTranscriptApi.get_transcript(vid)
    return [((s.start if hasattr(s, "start") else s["start"]),
             (s.text if hasattr(s, "text") else s["text"])) for s in segs], generated


def stamp(sec):
    """Seconds to MM:SS."""
    return f"{int(sec) // 60:02d}:{int(sec) % 60:02d}"


def to_prompt_text(segments, window=25):
    """Collapse segments into timestamped paragraphs so the model can cite moments."""
    lines, buf, t0 = [], [], None
    for start, text in segments:
        if t0 is None:
            t0 = start
        buf.append(text)
        if start - t0 >= window:
            lines.append(f"[{stamp(t0)}] " + " ".join(buf))
            buf, t0 = [], None
    if buf:
        lines.append(f"[{stamp(t0 or 0)}] " + " ".join(buf))
    return "\n".join(lines)


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

PROMPT = """You are extracting places from a transcript of a travel video. It may be
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


def call_gemini(model, api_key, prompt, ca=None):
    """POST to generateContent with a JSON schema. Returns (parsed, usage, seconds)."""
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseSchema": SCHEMA, "temperature": 0}}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f)
        path = f.name
    cmd = ["curl", "-sS", "--max-time", "300"]
    if ca:
        cmd += ["--cacert", ca]
    cmd += ["-H", "Content-Type: application/json", "-X", "POST",
            "--data-binary", f"@{path}", f"{API}/{model}:generateContent?key={api_key}"]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    os.unlink(path)
    try:
        d = json.loads(r.stdout)
    except Exception:
        sys.exit(f"non-JSON response (exit {r.returncode}): {r.stdout[:200]}{r.stderr[:200]}")
    if "error" in d:
        sys.exit(f"API error {d['error'].get('code')}: {d['error'].get('message','')[:250]}")
    return json.loads(d["candidates"][0]["content"]["parts"][0]["text"]), d.get("usageMetadata", {}), dt


def main():
    env = load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", default=env.get("YOUTUBE_VIDEO") or "VpkCSDYVaRc")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not found")
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    vid = video_id(args.video)

    segs, generated = fetch_transcript(vid)
    kind = "AUTO" if generated else ("MANUAL" if generated is False else "unknown")
    text = to_prompt_text(segs)
    result, usage, dt = call_gemini(args.model, key, PROMPT.format(transcript=text), ca)

    pin, pout = usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)
    print(f"{vid}  captions:{kind}  {len(segs)} segs  {dt:.1f}s  {pin}in/{pout}out")

    if not result.get("is_travel_content", True):
        print(f"  GATE REJECTED — {result.get('content_type', '?')} — nothing ingested")
    else:
        print(f"  gate ok — {result.get('content_type', '?')}  |  city: {result['city']} "
              f"({result['city_confidence']})")

    other = result.get("other_cities_mentioned") or []
    if other and not args.quiet:
        print(f"  other cities excluded: {', '.join(other)}")

    places = result.get("places", [])
    print(f"  {len(places)} places")
    if not args.quiet:
        for p in places:
            flag = "" if p["name_confidence"] == "high" else f"  [conf:{p['name_confidence']}]"
            price = f"  price:{p['spoken_price']}(unverified)" if p.get("spoken_price") else ""
            mark = {"recommended": "+", "mixed": "~", "not_recommended": "-"}.get(p["sentiment"], "?")
            print(f"   {mark} [{p['timestamp']}] {p['category'].upper():<5} {p['name']}{flag}{price}")
            print(f"       {p['why_go']}")
        for r in result.get("rejected") or []:
            print(f"   x {r['text']}: {r['reason']}")

    if args.json:
        json.dump({"video_id": vid, "captions": kind, "usage": usage, "result": result},
                  open(args.json, "w"), indent=2, ensure_ascii=False)
        print(f"  wrote {args.json}")


if __name__ == "__main__":
    main()
