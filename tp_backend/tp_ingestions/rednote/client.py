"""RedNote's private web API. Ported from spikes/xhs/{call,food_spike}.py, on httpx.

Callers must pass the RedNote budget first — see throttle.py for why that is not optional.
"""

import logging
import re
import uuid

import httpx

from libs.db.enums import ErrorCode
from libs.http import client
from libs.settings import settings
from tp_ingestions.errors import TaskError

SEARCH_URL = "https://webapi.rednote.com/api/sns/web/v1/search/notes"
FEED_URL = "https://webapi.rednote.com/api/sns/web/v1/feed"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# The API answers "not logged in" in prose rather than a stable code, so match the wording.
AUTH_HINTS = ("登录", "login", "登陆", "验证")

log = logging.getLogger("rednote.client")


def _headers(endpoint: str) -> dict[str, str]:
    """Signature headers for one endpoint. x-s is bound to the URL path, so search's will not
    authenticate against /feed — each endpoint needs its own capture."""
    s = settings()
    prefix = f"XHS_{endpoint.upper()}_"
    xs, xt = getattr(s, f"xhs_{endpoint}_xs"), getattr(s, f"xhs_{endpoint}_xt")
    common, rap = getattr(s, f"xhs_{endpoint}_xs_common"), getattr(s, f"xhs_{endpoint}_xrap")
    missing = [n for n, v in (("XHS_COOKIE", s.xhs_cookie), (prefix + "XS", xs),
                              (prefix + "XT", xt), (prefix + "XS_COMMON", common)) if not v]
    if missing:
        raise TaskError(ErrorCode.CREDENTIALS, f"missing RedNote credentials: {', '.join(missing)}")

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.rednote.com",
        "referer": "https://www.rednote.com/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": UA,
        "cookie": s.xhs_cookie,
        "x-s": xs,
        "x-t": xt,
        "x-s-common": common,
        "xy-common-params": "mlanguage=en_us&appKey=rednote",
    }
    if rap:
        headers["x-rap-param"] = rap
    return headers


def likes(raw: str | None) -> int:
    """'196' or '1.2万' to an int."""
    text = (raw or "0").strip()
    m = re.fullmatch(r"([\d.]+)万", text)
    if m:
        return int(float(m.group(1)) * 10000)
    return int(re.sub(r"\D", "", text) or 0)


def _post(url: str, endpoint: str, body: dict) -> dict:
    try:
        r = client().post(url, json=body, headers=_headers(endpoint))
    except httpx.HTTPError as e:
        raise TaskError(ErrorCode.TRANSIENT, f"rednote: {e}") from e

    if r.status_code in (401, 403, 461, 471):
        raise TaskError(ErrorCode.CREDENTIALS, f"rednote {r.status_code}: {r.text[:200]}")
    if r.status_code == 429:
        raise TaskError(ErrorCode.RATE_LIMITED, f"rednote 429: {r.text[:200]}")
    if r.status_code != 200:
        raise TaskError(ErrorCode.TRANSIENT, f"rednote {r.status_code}: {r.text[:200]}")

    try:
        data = r.json()
    except ValueError as e:
        raise TaskError(ErrorCode.TRANSIENT, f"rednote non-JSON: {r.text[:200]}") from e

    if not data.get("success"):
        msg = str(data.get("msg", ""))
        code = data.get("code")
        # A throttled call can answer 200 with zero results, so never read "empty" as "done".
        if any(h in msg for h in AUTH_HINTS):
            raise TaskError(ErrorCode.CREDENTIALS, f"rednote code={code} msg={msg[:120]}")
        raise TaskError(ErrorCode.TRANSIENT, f"rednote code={code} msg={msg[:120]}")
    return data


def search_notes(keyword: str, page: int = 1, page_size: int = 20) -> list[dict]:
    """Note stubs in the API's own relevance order, which surfaces text-rich posts."""
    body = {"keyword": keyword, "page": page, "page_size": page_size,
            "search_id": uuid.uuid4().hex[:21], "sort": "general", "note_type": 0,
            "ext_flags": [], "geo": "", "image_formats": ["jpg", "webp", "avif"]}
    data = _post(SEARCH_URL, "search", body)

    notes = []
    for item in (data.get("data") or {}).get("items") or []:
        card = item.get("note_card") or {}
        if not card.get("display_title"):
            continue
        notes.append({
            "note_id": item["id"],
            "xsec_token": item.get("xsec_token"),
            "title": card["display_title"],
            "likes": likes((card.get("interact_info") or {}).get("liked_count")),
            "author": (card.get("user") or {}).get("nickname"),
        })
    return notes


def fetch_note(note_id: str, xsec_token: str | None) -> dict | None:
    """One note's full body from /feed. Returns its note_card, or None if the feed had no item."""
    body = {"source_note_id": note_id, "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": "1"}, "xsec_source": "pc_feed",
            "xsec_token": xsec_token, "need_translation": 1}
    data = _post(FEED_URL, "feed", body)
    items = (data.get("data") or {}).get("items") or []
    return (items[0].get("note_card") or None) if items else None
