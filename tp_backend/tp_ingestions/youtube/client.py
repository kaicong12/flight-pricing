"""YouTube Data API v3. Ported from spikes/videos_transcribing/youtube_search.py, on httpx."""

import re

import httpx

from libs.db.enums import ErrorCode
from libs.http import client
from libs.settings import settings
from tp_ingestions.errors import TaskError

API = "https://www.googleapis.com/youtube/v3"

# search.list draws on its own 100-calls-a-day bucket, so one call per language per city is the
# whole budget decision.
SEARCH_UNITS = 1


def _get(path: str, params: dict) -> dict:
    key = settings().google_api_key
    if not key:
        raise TaskError(ErrorCode.CREDENTIALS, "GOOGLE_API_KEY is not set")
    try:
        r = client().get(f"{API}/{path}", params={**params, "key": key})
    except httpx.HTTPError as e:
        raise TaskError(ErrorCode.TRANSIENT, f"{path}: {e}") from e

    if r.status_code == 200:
        return r.json()

    detail = r.text[:300]
    reason = ""
    try:
        errors = r.json().get("error", {}).get("errors") or [{}]
        reason = errors[0].get("reason", "")
    except ValueError:
        pass
    if r.status_code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded",
                                          "rateLimitExceeded"):
        raise TaskError(ErrorCode.QUOTA, f"{path}: {reason}")
    if r.status_code == 403:
        raise TaskError(ErrorCode.CREDENTIALS, f"{path}: {reason or detail}")
    if r.status_code == 429:
        raise TaskError(ErrorCode.RATE_LIMITED, f"{path}: {detail}")
    if 400 <= r.status_code < 500:
        raise TaskError(ErrorCode.PERMANENT, f"{path} {r.status_code}: {detail}")
    raise TaskError(ErrorCode.TRANSIENT, f"{path} {r.status_code}: {detail}")


def iso_seconds(s: str) -> int:
    """PT23M25S to seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, sec = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + sec


def search(query: str, lang: str | None = None, region: str | None = None,
           published_after: str | None = None, limit: int = 10) -> list[dict]:
    params = {"part": "snippet", "q": query, "type": "video", "maxResults": limit,
              "order": "relevance", "videoEmbeddable": "true"}
    if lang:
        params["relevanceLanguage"] = lang
    if region:
        params["regionCode"] = region
    if published_after:
        params["publishedAfter"] = published_after
    data = _get("search", params)
    return [{"video_id": i["id"]["videoId"],
             "title": i["snippet"]["title"],
             "channel": i["snippet"]["channelTitle"],
             "published_at": i["snippet"]["publishedAt"]}
            for i in data.get("items", []) if i.get("id", {}).get("videoId")]


def hydrate(video_ids: list[str]) -> dict[str, dict]:
    """videos.list — duration, views, caption flag. One unit per 50 ids."""
    if not video_ids:
        return {}
    out = {}
    for chunk in (video_ids[i:i + 50] for i in range(0, len(video_ids), 50)):
        data = _get("videos", {"part": "contentDetails,statistics,snippet", "id": ",".join(chunk)})
        for item in data.get("items", []):
            content, stats, snip = item["contentDetails"], item.get("statistics", {}), item["snippet"]
            out[item["id"]] = {
                "duration_s": iso_seconds(content.get("duration", "")),
                # contentDetails.caption is true only when the uploader supplied subtitles, which is
                # what distinguishes them from ASR.
                "captions": "MANUAL" if content.get("caption") == "true" else "AUTO",
                "view_count": int(stats.get("viewCount", 0)),
                "description": snip.get("description", ""),
                "lang": snip.get("defaultAudioLanguage") or snip.get("defaultLanguage"),
            }
    return out
