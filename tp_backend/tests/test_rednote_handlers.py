"""rednote.fetch / extract / ocr: the one-transaction guarantee, the OCR gate, the pay-once skip."""

import pytest
from conftest import HELSINKI, make_city
from sqlalchemy import select

from libs.db import Extraction, IngestRun, IngestTask, RedNotePost
from libs.db.enums import (
    ErrorCode,
    ExtractedFrom,
    RunKind,
    RunStatus,
    Source,
    TaskKind,
    TaskStatus,
)
from libs.prompts import REDNOTE_OCR, REDNOTE_TEXT
from tp_ingestions.errors import TaskError
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.rednote import extract, fetch, ocr
from tp_ingestions.worker import Worker

NOTE = "68f0aa1c000000000e0139c4"

CARD = {
    "note_id": NOTE,
    "title": "特罗姆瑟美食",
    "desc": "第一家 Tang's 很好吃",
    "time": 1770919541000,
    "note_translation": {"desc_trans": "The first one, Tang's, is delicious"},
    "tag_list": [{"id": "1", "name": "特罗姆瑟", "type": "topic"}],
    "image_list": [{"url_pre": "http://cdn/pre1.jpg",
                    "info_list": [{"image_scene": "WB_DFT", "url": "http://cdn/dft1.jpg"},
                                  {"image_scene": "WB_PRV", "url": "http://cdn/prv1.jpg"}]}],
}


def result(places=(), **kw):
    return {"is_useful": bool(places), "content_type": "food guide", "is_promotional": False,
            "city": "Helsinki", "city_confidence": "high", "places": list(places)} | kw


def place(name="Tang's"):
    return {"name_as_written": name, "name_local": name, "name_local_confidence": "unknown",
            "category": "eat", "why_go": "the post says it is delicious",
            "sentiment": "recommended"}


@pytest.fixture
def run(db):
    make_city(db)
    r = IngestRun(run_id="run-1", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                  status=RunStatus.RUNNING)
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def post(db):
    """The stub row rednote.search inserts before any fetch runs."""
    p = RedNotePost(note_id=NOTE, xsec_token="tok", title="特罗姆瑟美食", likes=196)
    db.add(p)
    db.commit()
    return p


def task(run, kind=TaskKind.REDNOTE_FETCH, **payload):
    return ClaimedTask(task_id=1, run_id=run.run_id, kind=kind, source=Source.REDNOTE,
                       payload={"note_id": NOTE, "city_id": HELSINKI} | payload,
                       attempts=1, max_attempts=5)


def queued_task(db, run, kind=TaskKind.REDNOTE_FETCH, **payload):
    """A real queue row, so the worker can claim it and own the transaction."""
    db.add(IngestTask(run_id=run.run_id, kind=kind, source=Source.REDNOTE,
                      payload={"note_id": NOTE, "city_id": HELSINKI} | payload,
                      dedupe_key=f"{kind}:{NOTE}"))
    db.commit()


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr("tp_ingestions.rednote.throttle.await_budget", lambda: None)
    monkeypatch.setattr(fetch, "await_budget", lambda: None)
    return Worker(name="w1", poll_interval=0, reap_interval=1e9)


def test_fetch_stores_the_note_body(db, run, post, monkeypatch):
    monkeypatch.setattr(fetch, "await_budget", lambda: None)
    monkeypatch.setattr(fetch.client, "fetch_note", lambda n, t: CARD)
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))

    fetch.rednote_fetch(db, task(run))
    db.commit()

    row = db.get(RedNotePost, NOTE)
    assert row.description == "第一家 Tang's 很好吃"
    assert row.description_en == "The first one, Tang's, is delicious"
    assert row.tags == ["特罗姆瑟"]
    assert row.image_urls == ["https://cdn/prv1.jpg"]
    assert row.posted_at.year == 2026


def test_fetch_strips_zero_width_characters_from_the_body(db, run, post, monkeypatch):
    """Some notes separate every letter of a venue name, which would wreck name extraction."""
    monkeypatch.setattr(fetch, "await_budget", lambda: None)
    monkeypatch.setattr(fetch.client, "fetch_note",
                        lambda n, t: CARD | {"desc": "T\u200bang's\nR\u200be"})
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result())

    fetch.rednote_fetch(db, task(run))
    db.commit()

    # The newline survives: Cc is left alone because it is the post's paragraph structure.
    assert db.get(RedNotePost, NOTE).description == "Tang's\nRe"


def test_fetch_of_a_bodyless_note_is_permanent(db, run, post, monkeypatch):
    monkeypatch.setattr(fetch, "await_budget", lambda: None)
    monkeypatch.setattr(fetch.client, "fetch_note", lambda n, t: None)

    with pytest.raises(TaskError) as e:
        fetch.rednote_fetch(db, task(run))
    assert e.value.code == ErrorCode.PERMANENT


def test_the_body_and_its_extraction_commit_together(db, run, post, worker, monkeypatch):
    """A Gemini failure must leave no description and no extraction — one note, one transaction."""
    queued_task(db, run)
    monkeypatch.setattr(fetch.client, "fetch_note", lambda n, t: CARD)

    def boom(*a, **k):
        raise TaskError(ErrorCode.TRANSIENT, "gemini 500")

    monkeypatch.setattr(extract.gemini, "generate", boom)
    worker.run_once()

    db.expire_all()
    assert db.get(RedNotePost, NOTE).description is None
    assert db.scalars(select(Extraction)).all() == []


def test_a_successful_fetch_writes_both_in_one_go(db, run, post, worker, monkeypatch):
    queued_task(db, run)
    monkeypatch.setattr(fetch.client, "fetch_note", lambda n, t: CARD)
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))

    worker.run_once()

    db.expire_all()
    assert db.get(RedNotePost, NOTE).description is not None
    row = db.scalars(select(Extraction)).one()
    assert (row.source, row.source_ref) == (Source.REDNOTE, NOTE)
    assert (row.place_count, row.extracted_from) == (1, ExtractedFrom.TEXT)
    assert row.result["places"][0]["name_as_written"] == "Tang's"


def ocr_tasks(db) -> list[str]:
    return db.scalars(select(IngestTask.kind).where(IngestTask.kind == TaskKind.REDNOTE_OCR)).all()


def prepared(db, description="第一家很好吃", images=("https://cdn/prv1.jpg",)):
    post = db.get(RedNotePost, NOTE)
    post.description = description
    post.image_urls = list(images) if images else None
    db.commit()
    return post


def test_ocr_is_queued_when_the_text_named_nothing(db, run, post, monkeypatch):
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result())
    extract.extract_note(db, task(run), prepared(db))
    db.commit()
    assert ocr_tasks(db) == [TaskKind.REDNOTE_OCR]


def test_ocr_is_not_queued_when_the_text_named_places(db, run, post, monkeypatch):
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))
    extract.extract_note(db, task(run), prepared(db))
    db.commit()
    assert ocr_tasks(db) == []


def test_ocr_is_not_queued_when_the_post_has_no_images(db, run, post, monkeypatch):
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result())
    extract.extract_note(db, task(run), prepared(db, images=None))
    db.commit()
    assert ocr_tasks(db) == []


def test_an_already_extracted_note_is_not_paid_for_twice(db, run, post, monkeypatch):
    prepared(db)
    db.add(Extraction(source=Source.REDNOTE, source_ref=NOTE,
                      prompt_version=REDNOTE_TEXT.version_key, model=REDNOTE_TEXT.model,
                      extracted_from=ExtractedFrom.TEXT, is_useful=False, is_promotional=False,
                      place_count=0))
    db.commit()

    def never(*a, **k):
        raise AssertionError("gemini was called for a note already extracted")

    monkeypatch.setattr(extract.gemini, "generate", never)
    assert extract.extract_note(db, task(run), db.get(RedNotePost, NOTE))["cached"] is True


def test_ocr_reads_the_downloaded_cards(db, run, post, monkeypatch):
    prepared(db)
    seen = {}

    def generate(prompt, rendered, images=None):
        seen["prompt"], seen["images"] = prompt, images
        return result([place("Bardus")])

    monkeypatch.setattr(ocr, "download", lambda urls: [b"\xff\xd8\xff\xe0jpeg"])
    monkeypatch.setattr(ocr.gemini, "generate", generate)

    ocr.rednote_ocr(db, task(run, kind=TaskKind.REDNOTE_OCR))
    db.commit()

    assert seen["prompt"] is REDNOTE_OCR
    assert seen["images"] == [b"\xff\xd8\xff\xe0jpeg"]
    row = db.scalars(select(Extraction)).one()
    assert (row.extracted_from, row.place_count) == (ExtractedFrom.IMAGE, 1)


def test_ocr_with_no_downloadable_card_is_permanent(db, run, post, monkeypatch):
    prepared(db)
    monkeypatch.setattr(ocr, "download", lambda urls: [])

    with pytest.raises(TaskError) as e:
        ocr.rednote_ocr(db, task(run, kind=TaskKind.REDNOTE_OCR))
    assert e.value.code == ErrorCode.PERMANENT


def test_ocr_downloads_at_most_the_configured_number_of_cards(db, run, post, monkeypatch):
    prepared(db, images=[f"https://cdn/{i}.jpg" for i in range(9)])
    asked = []

    def download(urls):
        asked.extend(urls)
        return [b"jpg"]

    monkeypatch.setattr(ocr, "download", download)
    monkeypatch.setattr(ocr.gemini, "generate", lambda *a, **k: result())

    ocr.rednote_ocr(db, task(run, kind=TaskKind.REDNOTE_OCR))

    assert len(asked) == 4


def test_a_search_caps_its_fetch_fan_out(db, run, monkeypatch):
    """page_size is 20 but MAX_PER_HOUR is 20, so one city must not spend the whole hour."""
    from tp_ingestions.rednote import search

    notes = [{"note_id": f"n{i}", "xsec_token": "t", "title": f"t{i}", "likes": i, "author": "a"}
             for i in range(20)]
    monkeypatch.setattr(search, "await_budget", lambda: None)
    monkeypatch.setattr(search.client, "search_notes", lambda kw: notes)

    out = search.rednote_search(db, task(run, kind=TaskKind.REDNOTE_SEARCH, keyword="Tromsø 美食"))
    db.commit()

    assert (out["found"], out["queued"]) == (20, 8)
    assert db.scalar(select(IngestTask.payload["note_id"].as_string())) == "n0"


def test_a_search_task_that_never_ran_leaves_fetch_permanent(db, run, monkeypatch):
    monkeypatch.setattr(fetch, "await_budget", lambda: None)
    with pytest.raises(TaskError) as e:
        fetch.rednote_fetch(db, task(run))
    assert e.value.code == ErrorCode.PERMANENT


def test_a_blocked_kind_no_longer_happens_for_rednote(db, run, post, worker, monkeypatch):
    """The four new handlers exist, so nothing in the RedNote chain lands in queue.block."""
    queued_task(db, run)
    monkeypatch.setattr(fetch.client, "fetch_note", lambda n, t: CARD)
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))

    worker.run_once()

    db.expire_all()
    assert db.scalars(select(IngestTask.status)).all() == [TaskStatus.DONE]
