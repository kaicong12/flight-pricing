"""rednote.fetch — pull one note's full body from /feed, then extract it in the same transaction."""

import logging
import unicodedata
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from libs.db import RedNotePost
from libs.db.enums import ErrorCode, TaskKind
from tp_ingestions import limits
from tp_ingestions.errors import TaskError
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.rednote import client
from tp_ingestions.rednote.extract import extract_note
from tp_ingestions.registry import handles

log = logging.getLogger("rednote.fetch")


def preview_urls(note_card: dict) -> list[str]:
    """Preview-sized image URLs, cheapest variant first — Gemini bills images by resolution."""
    out = []
    for img in note_card.get("image_list") or []:
        url = next((i["url"] for i in img.get("info_list") or []
                    if i.get("image_scene") == "WB_PRV" and i.get("url")), None)
        url = url or img.get("url_pre") or img.get("url_default") or img.get("url")
        if url:
            out.append(url.replace("http://", "https://"))
    return out


def tag_names(note_card: dict) -> list[str]:
    items = note_card.get("tag_list") or []
    return [t["name"] for t in items if isinstance(t, dict) and t.get("name")]


def posted_at(note_card: dict) -> datetime | None:
    """note_card.time is epoch milliseconds, not seconds."""
    ms = note_card.get("time")
    return datetime.fromtimestamp(ms / 1000, UTC) if isinstance(ms, int | float) and ms else None


def translated(note_card: dict) -> str | None:
    """The English body the request's need_translation=1 asks for."""
    value = (note_card.get("note_translation") or {}).get("desc_trans")
    return value if isinstance(value, str) and value.strip() else None


def clean(desc: str) -> str:
    # Some notes separate every letter of a venue name with zero-width chars. Cc is left alone —
    # newlines and tabs are the post's paragraph structure.
    return "".join(c for c in desc if unicodedata.category(c) != "Cf")


@handles(TaskKind.REDNOTE_FETCH)
def rednote_fetch(session: Session, task: ClaimedTask) -> dict:
    note_id = task.payload["note_id"]
    note = session.get(RedNotePost, note_id)
    if note is None:
        raise TaskError(ErrorCode.PERMANENT, f"rednote note {note_id} was never inserted by search")

    limits.rednote().take()
    card = client.fetch_note(note_id, task.payload.get("xsec_token") or note.xsec_token)
    if not card or not (card.get("desc") or "").strip():
        raise TaskError(ErrorCode.PERMANENT, f"rednote note {note_id} returned no body")

    note.description = clean(card["desc"])
    note.description_en = translated(card)
    note.image_urls = preview_urls(card)
    note.tags = tag_names(card)
    note.posted_at = posted_at(card)
    if card.get("title"):
        note.title = card["title"]
    session.flush()

    # A child call, not an enqueued task: the body and its extraction commit or roll back together.
    return {"note_id": note_id, "chars": len(note.description),
            "images": len(note.image_urls), **extract_note(session, task, note)}
