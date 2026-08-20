"""generateContent against the Gemini REST API, on httpx rather than google-genai.

Schema-constrained JSON only: responseSchema accepts an OpenAPI-3.0 subset, and the prompt schemas in
libs/prompts stay inside it (type/properties/required/enum/items — no $ref, oneOf or additionalProperties).
"""

import base64
import json
import logging

import httpx

from libs.db.enums import ErrorCode
from libs.http import client
from libs.prompts import Prompt
from libs.settings import settings
from tp_ingestions.errors import TaskError

API = "https://generativelanguage.googleapis.com/v1beta/models"

QUOTA_HINTS = ("quota", "RESOURCE_EXHAUSTED")
AUTH_REASONS = ("API_KEY_INVALID", "PERMISSION_DENIED", "API key not valid", "UNAUTHENTICATED")

log = logging.getLogger("gemini")


def _mime(data: bytes) -> str:
    """Sniff the image type from its magic number — a RedNote CDN URL does not carry the format."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[4:12] == b"ftypavif":
        return "image/avif"
    return "image/jpeg"


def _classify(status: int, body: str) -> TaskError:
    quota = any(h.lower() in body.lower() for h in QUOTA_HINTS)
    if status == 429:
        return TaskError(ErrorCode.QUOTA if quota else ErrorCode.RATE_LIMITED,
                         f"gemini 429: {body[:200]}")
    if status == 403 and quota:
        return TaskError(ErrorCode.QUOTA, f"gemini 403: {body[:200]}")
    if status == 401 or (status == 403 and any(r in body for r in AUTH_REASONS)):
        return TaskError(ErrorCode.CREDENTIALS, f"gemini {status}: {body[:200]}")
    if status == 403:
        return TaskError(ErrorCode.CREDENTIALS, f"gemini 403: {body[:200]}")
    if status in (400, 404):
        return TaskError(ErrorCode.PERMANENT, f"gemini {status}: {body[:200]}")
    return TaskError(ErrorCode.TRANSIENT, f"gemini {status}: {body[:200]}")


def generate(prompt: Prompt, rendered: str, images: list[bytes] | None = None) -> dict:
    """One schema-constrained call. Returns the parsed object the model produced."""
    key = settings().gemini_api_key
    if not key:
        raise TaskError(ErrorCode.CREDENTIALS, "GEMINI_API_KEY is not set")

    parts: list[dict] = [{"text": rendered}]
    for data in images or []:
        parts.append({"inline_data": {"mime_type": _mime(data),
                                      "data": base64.b64encode(data).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseSchema": prompt.schema, "temperature": 0}}

    url = f"{API}/{prompt.model}:generateContent"
    try:
        r = client().post(url, params={"key": key}, json=body)
    except httpx.HTTPError as e:
        raise TaskError(ErrorCode.TRANSIENT, f"gemini: {e}") from e
    if r.status_code != 200:
        raise _classify(r.status_code, r.text)

    data = r.json()
    usage = data.get("usageMetadata") or {}
    log.info("%s %s: %sin/%sout tokens", prompt.name, prompt.model,
             usage.get("promptTokenCount"), usage.get("candidatesTokenCount"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise TaskError(ErrorCode.TRANSIENT,
                        f"gemini returned no candidates: {str(data.get('promptFeedback'))[:200]}")
    finish = candidates[0].get("finishReason")
    if finish in ("MAX_TOKENS", "SAFETY"):
        raise TaskError(ErrorCode.TRANSIENT, f"gemini finishReason={finish}")

    text = ((candidates[0].get("content") or {}).get("parts") or [{}])[0].get("text") or ""
    try:
        return json.loads(text)
    except ValueError as e:
        raise TaskError(ErrorCode.TRANSIENT, f"gemini non-JSON body: {text[:200]}") from e
