"""youtube.extract: transcript caching, the pay-once skip, and the non-travel gate."""

import pytest
from conftest import HELSINKI, make_city
from sqlalchemy import select

from libs.db import Extraction, IngestRun, YouTubeVideo
from libs.db.enums import ErrorCode, ExtractedFrom, RunKind, RunStatus, Source, TaskKind
from libs.prompts import YOUTUBE_TRANSCRIPT
from tp_ingestions.errors import TaskError
from tp_ingestions.queue import ClaimedTask
from tp_ingestions.youtube import extract, transcript

VIDEO = "VpkCSDYVaRc"


def result(places=(), travel=True, **kw):
    return {"is_travel_content": travel, "content_type": "travel guide", "city": "Helsinki",
            "city_confidence": "high", "places": list(places)} | kw


def place(name="Löyly"):
    return {"name": name, "name_confidence": "high", "category": "do", "timestamp": "04:12",
            "why_go": "a seaside sauna the host rates", "sentiment": "recommended"}


@pytest.fixture
def run(db):
    make_city(db)
    r = IngestRun(run_id="run-1", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                  status=RunStatus.RUNNING)
    db.add(r)
    db.commit()
    return r


@pytest.fixture
def video(db):
    v = YouTubeVideo(video_id=VIDEO, title="Helsinki in a day", channel="ch", captions="MANUAL")
    db.add(v)
    db.commit()
    return v


def task(run):
    return ClaimedTask(task_id=1, run_id=run.run_id, kind=TaskKind.YOUTUBE_EXTRACT,
                       source=Source.YOUTUBE, payload={"video_id": VIDEO, "city_id": HELSINKI},
                       attempts=1, max_attempts=5)


def never(*a, **k):
    raise AssertionError("the transcript fetcher was called when it should not have been")


def test_a_cached_transcript_is_reused_without_fetching(db, run, video, monkeypatch):
    video.transcript = "[00:00] welcome to Helsinki"
    db.commit()
    sent = {}

    def generate(prompt, rendered, images=None):
        sent["rendered"] = rendered
        return result([place()])

    monkeypatch.setattr(extract.tx, "fetch_transcript", never)
    monkeypatch.setattr(extract.gemini, "generate", generate)

    extract.youtube_extract(db, task(run))
    db.commit()

    assert "welcome to Helsinki" in sent["rendered"]


def test_an_absent_transcript_is_fetched_and_stored(db, run, video, monkeypatch):
    monkeypatch.setattr(extract.tx, "fetch_transcript",
                        lambda vid: [(0.0, "hello"), (30.0, "Löyly is next")])
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))

    extract.youtube_extract(db, task(run))
    db.commit()

    stored = db.get(YouTubeVideo, VIDEO).transcript
    assert stored == "[00:00] hello Löyly is next"


def test_an_already_extracted_video_is_not_paid_for_twice(db, run, video, monkeypatch):
    db.add(Extraction(source=Source.YOUTUBE, source_ref=VIDEO,
                      prompt_version=YOUTUBE_TRANSCRIPT.version_key,
                      model=YOUTUBE_TRANSCRIPT.model, extracted_from=ExtractedFrom.TEXT,
                      is_useful=False, is_promotional=False, place_count=0))
    db.commit()
    monkeypatch.setattr(extract.tx, "fetch_transcript", never)
    monkeypatch.setattr(extract.gemini, "generate", never)

    assert extract.youtube_extract(db, task(run))["cached"] is True


def test_a_non_travel_video_still_gets_its_row(db, run, video, monkeypatch):
    """is_useful=False is what stops us paying to re-read a tennis vlog."""
    monkeypatch.setattr(extract.tx, "fetch_transcript", lambda vid: [(0.0, "match point")])
    monkeypatch.setattr(extract.gemini, "generate",
                        lambda *a, **k: result(travel=False, content_type="tennis vlog"))

    extract.youtube_extract(db, task(run))
    db.commit()

    row = db.scalars(select(Extraction)).one()
    assert (row.is_useful, row.place_count, row.content_type) == (False, 0, "tennis vlog")


def test_the_whole_model_output_is_kept_as_json(db, run, video, monkeypatch):
    monkeypatch.setattr(extract.tx, "fetch_transcript", lambda vid: [(0.0, "hi")])
    monkeypatch.setattr(extract.gemini, "generate",
                        lambda *a, **k: result([place()], rejected=[{"text": "Haneda",
                                                                    "reason": "airport"}]))

    extract.youtube_extract(db, task(run))
    db.commit()

    stored = db.scalars(select(Extraction)).one().result
    assert stored["rejected"][0]["text"] == "Haneda"
    assert stored["city_confidence"] == "high"


def test_a_video_search_never_inserted_is_permanent(db, run):
    with pytest.raises(TaskError) as e:
        extract.youtube_extract(db, task(run))
    assert e.value.code == ErrorCode.PERMANENT


def test_extract_enqueues_nothing_downstream(db, run, video, monkeypatch):
    from libs.db import IngestTask

    monkeypatch.setattr(extract.tx, "fetch_transcript", lambda vid: [(0.0, "hi")])
    monkeypatch.setattr(extract.gemini, "generate", lambda *a, **k: result([place()]))

    extract.youtube_extract(db, task(run))
    db.commit()

    assert db.scalars(select(IngestTask.kind)).all() == []


def test_segments_collapse_into_timestamped_windows():
    """A window closes on the segment that crosses it, so the next line is stamped at its own start."""
    segments = [(0.0, "a"), (10.0, "b"), (26.0, "c"), (40.0, "d")]
    assert transcript.to_prompt_text(segments) == "[00:00] a b c\n[00:40] d"


def test_transcript_errors_are_classified_not_raised_raw(monkeypatch):
    """Waiting cannot enable subtitles, so a disabled transcript must be terminal."""
    import youtube_transcript_api as yta

    def disabled(self, vid):
        raise yta.TranscriptsDisabled(vid)

    monkeypatch.setattr(yta.YouTubeTranscriptApi, "fetch", disabled)
    with pytest.raises(TaskError) as e:
        transcript.fetch_transcript(VIDEO)
    assert e.value.code == ErrorCode.PERMANENT


def test_an_ip_block_is_rate_limited_not_permanent(monkeypatch):
    """A datacenter IP getting blocked is an environment problem, so it must stay visibly retryable."""
    import youtube_transcript_api as yta

    def blocked(self, vid):
        raise yta.RequestBlocked(vid)

    monkeypatch.setattr(yta.YouTubeTranscriptApi, "fetch", blocked)
    with pytest.raises(TaskError) as e:
        transcript.fetch_transcript(VIDEO)
    assert e.value.code == ErrorCode.RATE_LIMITED


def test_the_exception_names_resolve_against_the_installed_version():
    """1.x dropped TooManyRequests, so the lookup must tolerate a name that is not there."""
    assert transcript.PERMANENT and transcript.RATE_LIMITED
    assert all(issubclass(e, BaseException)
               for e in transcript.PERMANENT + transcript.RATE_LIMITED)
