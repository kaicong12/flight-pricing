"""RedNote's private web API. Ported from spikes/xhs/{call,food_spike}.py, on httpx.

Every call goes through the throttle first — see throttle.py for why that is not optional.
"""

import logging
import re
import uuid

import httpx

from libs.db.enums import ErrorCode
from libs.http import client
from libs.settings import settings
from tp_ingestions.errors import TaskError
from tp_ingestions.rednote import throttle

SEARCH_URL = "https://webapi.rednote.com/api/sns/web/v1/search/notes"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# The API answers "not logged in" in prose rather than a stable code, so match the wording.
AUTH_HINTS = ("登录", "login", "登陆", "验证")

log = logging.getLogger("rednote.client")


def _headers() -> dict[str, str]:
    s = settings()
    missing = [n for n, v in (("XHS_COOKIE", s.xhs_cookie),
                              ("XHS_SEARCH_XS", s.xhs_search_xs),
                              ("XHS_SEARCH_XT", s.xhs_search_xt),
                              ("XHS_SEARCH_XS_COMMON", s.xhs_search_xs_common)) if not v]
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
        "x-s": s.xhs_search_xs,
        "x-t": s.xhs_search_xt,
        "x-s-common": s.xhs_search_xs_common,
        "xy-common-params": "mlanguage=en_us&appKey=rednote",
    }
    if s.xhs_search_xrap:
        headers["x-rap-param"] = s.xhs_search_xrap
    return headers


def likes(raw: str | None) -> int:
    """'196' or '1.2万' to an int."""
    text = (raw or "0").strip()
    m = re.fullmatch(r"([\d.]+)万", text)
    if m:
        return int(float(m.group(1)) * 10000)
    return int(re.sub(r"\D", "", text) or 0)


def _post(url: str, body: dict) -> dict:
    throttle.record()
    try:
        r = client().post(url, json=body, headers=_headers())
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
    data = _post(SEARCH_URL, body)

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
