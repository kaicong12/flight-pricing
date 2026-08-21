"""places.resolve against stubbed Places. The cache, the geofence, and the merge on place_id."""

import pytest
from conftest import HELSINKI, make_city
from sqlalchemy import select

from libs.db import Extraction, IngestRun, Place, PlaceMention, PlaceQuery
from libs.db.enums import (
    Confidence,
    ErrorCode,
    ExtractedFrom,
    RunKind,
    RunStatus,
    Source,
    TaskKind,
)
from libs.places import PlacesError, VenueHit
from libs.prompts import REDNOTE_OCR, REDNOTE_TEXT, YOUTUBE_TRANSCRIPT
from tp_ingestions.errors import TaskError
from tp_ingestions.places import resolve
from tp_ingestions.queue import ClaimedTask

VIDEO = "vid0000001a"
NOTE = "68f0aa1c000000000e0139c4"


def hit(place_id="pid-1", name="Old Market Hall", lat=60.166, lon=24.951, count=8000, **kw):
    return VenueHit(**{"place_id": place_id, "name": name, "address": "Etelaranta 1",
                       "lat": lat, "lon": lon, "rating": 4.5, "rating_count": count,
                       "primary_type": "Market", "types": ["tourist_attraction"]} | kw)


def yt_place(name="Vanha Kauppahalli", **kw):
    return {"name": name, "name_confidence": "high", "category": "eat", "timestamp": "03:00",
            "why_go": "the old market hall", "sentiment": "recommended"} | kw


def rn_place(name="Löyly", **kw):
    return {"name_as_written": name, "name_local": name, "name_local_confidence": "high",
            "category": "eat", "why_go": "the post rates it", "sentiment": "recommended"} | kw


@pytest.fixture
def run(db):
    make_city(db)
    r = IngestRun(run_id="run-1", city_id=HELSINKI, kind=RunKind.CITY_INGEST,
                  status=RunStatus.RUNNING)
    db.add(r)
    db.commit()
    return r


def extraction(db, places, source=Source.YOUTUBE, ref=VIDEO, prompt=YOUTUBE_TRANSCRIPT,
               extracted_from=ExtractedFrom.TEXT):
    key = "is_travel_content" if source == Source.YOUTUBE else "is_useful"
    db.add(Extraction(source=source, source_ref=ref, prompt_version=prompt.version_key,
                      model=prompt.model, extracted_from=extracted_from, is_useful=True,
                      is_promotional=False, content_type="guide", place_count=len(places),
                      result={key: True, "city": "Helsinki", "city_confidence": "high",
                              "places": places}))
    db.commit()
    return prompt


def task(run, source=Source.YOUTUBE, ref=VIDEO, prompt=YOUTUBE_TRANSCRIPT):
    return ClaimedTask(task_id=1, run_id=run.run_id, kind=TaskKind.PLACES_RESOLVE,
                       source=Source.PLACES,
                       payload={"source": str(source), "source_ref": ref,
                                "prompt_version": prompt.version_key, "model": prompt.model,
                                "city_id": HELSINKI},
                       attempts=1, max_attempts=5)


def stub(monkeypatch, fn):
    monkeypatch.setattr(resolve, "search_venue", fn)
    return fn


DEFAULT = object()


def counting(monkeypatch, result=DEFAULT):
    """A stub that records every query, so a test can prove a call did not happen."""
    calls = []

    def search(query, lat, lon, radius):
        calls.append(query)
        return hit() if result is DEFAULT else result

    stub(monkeypatch, search)
    return calls


def test_a_candidate_becomes_a_place_and_a_mention(db, run, monkeypatch):
    extraction(db, [yt_place()])
    counting(monkeypatch)

    out = resolve.places_resolve(db, task(run))
    db.commit()

    place = db.get(Place, "pid-1")
    mention = db.scalars(select(PlaceMention)).one()
    assert out["resolved"] == 1
    assert (place.name, place.city_id, place.rating_count) == ("Old Market Hall", HELSINKI, 8000)
    assert place.confidence == Confidence.HIGH
    assert (mention.source, mention.source_ref, mention.category) == (Source.YOUTUBE, VIDEO, "eat")
    assert mention.name_as_written == "Vanha Kauppahalli"
    assert mention.source_timestamp == "03:00"


def test_the_city_is_appended_to_the_query(db, run, monkeypatch):
    """Bare "Tromso Cathedral" resolves to a different church, so the suffix is load-bearing."""
    extraction(db, [yt_place()])
    calls = counting(monkeypatch)

    resolve.places_resolve(db, task(run))

    assert calls == ["Vanha Kauppahalli, Helsinki"]


def test_two_spellings_collapse_to_one_place_with_two_mentions(db, run, monkeypatch):
    """The whole design: Fjellheisen and Felheisen are one venue, and place_id is what says so."""
    extraction(db, [yt_place("Fjellheisen"), yt_place("Felheisen cable car")])
    calls = counting(monkeypatch)

    out = resolve.places_resolve(db, task(run))
    db.commit()

    assert len(calls) == 2
    assert len(db.scalars(select(Place)).all()) == 1
    # One extraction is one source_ref, so the unique constraint folds them into a single mention.
    assert len(db.scalars(select(PlaceMention)).all()) == 1
    assert out["candidates"] == 2


def test_the_same_venue_from_two_sources_is_one_place_with_two_mentions(db, run, monkeypatch):
    """Raketten Bar & Pølse from RedNote and Raken Bar and Pulse from a transcript."""
    extraction(db, [yt_place("Raken Bar and Pulse")])
    extraction(db, [rn_place("Raketten Bar & Pølse")], source=Source.REDNOTE, ref=NOTE,
               prompt=REDNOTE_TEXT)
    counting(monkeypatch)

    resolve.places_resolve(db, task(run))
    resolve.places_resolve(db, task(run, source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT))
    db.commit()

    assert len(db.scalars(select(Place)).all()) == 1
    assert {m.source for m in db.scalars(select(PlaceMention)).all()} == {Source.YOUTUBE,
                                                                         Source.REDNOTE}


def test_a_repeated_name_is_never_queried_twice(db, run, monkeypatch):
    extraction(db, [yt_place("Polar Museum"), yt_place("polar Museum")])
    calls = counting(monkeypatch)

    out = resolve.places_resolve(db, task(run))

    assert len(calls) == 1
    assert out["cached"] == 1


def test_a_second_run_over_the_same_names_calls_nothing(db, run, monkeypatch):
    """The cache is what makes re-running the resolver free, and repeat resolution consistent."""
    extraction(db, [yt_place()])
    counting(monkeypatch)
    resolve.places_resolve(db, task(run))
    db.commit()

    def never(*a, **k):
        raise AssertionError("Places was called for a name already in place_queries")

    stub(monkeypatch, never)
    out = resolve.places_resolve(db, task(run))

    assert out["cached"] == 1 and out["resolved"] == 0


def test_a_miss_is_not_cached(db, run, monkeypatch):
    """searchText answers a silent throttle with 200 and no results, which looks exactly like "no
    such place". Caching that would poison the name for good, so a later run must retry it."""
    extraction(db, [yt_place("Raken Bar and Pulse")])
    counting(monkeypatch, result=None)

    assert resolve.places_resolve(db, task(run))["rejected"] == 1
    db.commit()
    assert db.scalars(select(PlaceQuery)).all() == []

    # The same name resolves on a later run, which a cached miss would have made impossible.
    counting(monkeypatch)
    assert resolve.places_resolve(db, task(run))["resolved"] == 1


def test_a_name_that_misses_twice_in_one_extraction_costs_one_call(db, run, monkeypatch):
    """Not cached in Postgres, but not re-queried within the task either."""
    extraction(db, [yt_place("Senha"), yt_place("senha")])
    calls = counting(monkeypatch, result=None)

    out = resolve.places_resolve(db, task(run))

    assert len(calls) == 1 and out["rejected"] == 2


def test_a_result_outside_the_city_is_rejected(db, run, monkeypatch):
    """Sentra, an ASR garble, resolved to a business 350 km away."""
    extraction(db, [yt_place("Sentra")])
    counting(monkeypatch, result=hit(lat=64.0, lon=25.0))

    out = resolve.places_resolve(db, task(run))
    db.commit()

    assert out["rejected"] == 1
    assert db.scalars(select(Place)).all() == []
    assert db.scalars(select(PlaceQuery)).all() == []


def test_a_place_with_no_ratings_is_rejected(db, run, monkeypatch):
    extraction(db, [yt_place()])
    counting(monkeypatch, result=hit(count=0))

    out = resolve.places_resolve(db, task(run))
    db.commit()

    assert out["rejected"] == 1
    assert db.scalars(select(Place)).all() == []


def test_a_generic_noun_is_never_sent_to_google(db, run, monkeypatch):
    """Places answers "bakery" with a real 4.7-star bakery, so this must be gated before the call."""
    extraction(db, [yt_place("bakery"), yt_place("library")])
    calls = counting(monkeypatch)

    out = resolve.places_resolve(db, task(run))

    assert calls == [] and out["filtered"] == 2


def test_a_chain_is_never_sent_to_google(db, run, monkeypatch):
    extraction(db, [yt_place("McDonald's")])
    calls = counting(monkeypatch)

    assert resolve.places_resolve(db, task(run))["filtered"] == 1
    assert calls == []


def test_a_place_the_source_disliked_is_skipped(db, run, monkeypatch):
    """Gate on what the source said, never on the Google rating."""
    extraction(db, [yt_place(sentiment="not_recommended")])
    calls = counting(monkeypatch)

    assert resolve.places_resolve(db, task(run))["filtered"] == 1
    assert calls == []


def test_a_rednote_note_uses_the_local_name_when_the_model_knew_it(db, run, monkeypatch):
    extraction(db, [rn_place(name="Dragøy海鲜市场", name_local="Dragøy Kystens Mathus")],
               source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT)
    calls = counting(monkeypatch)

    resolve.places_resolve(db, task(run, source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT))

    assert calls == ["Dragøy Kystens Mathus, Helsinki"]


def test_a_rednote_note_falls_back_to_what_was_written(db, run, monkeypatch):
    extraction(db, [rn_place(name="Tang's Restaurant", name_local="Tang's Restaurant",
                             name_local_confidence="unknown")],
               source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT)
    calls = counting(monkeypatch)

    resolve.places_resolve(db, task(run, source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT))

    assert calls == ["Tang's Restaurant, Helsinki"]


def test_a_notes_text_and_ocr_passes_do_not_double_count_one_venue(db, run, monkeypatch):
    """uq_mention_place_source_ref omits prompt_version, so the later pass updates one mention."""
    extraction(db, [rn_place()], source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT)
    extraction(db, [rn_place(why_go="read off the image card")], source=Source.REDNOTE, ref=NOTE,
               prompt=REDNOTE_OCR, extracted_from=ExtractedFrom.IMAGE)
    counting(monkeypatch)

    resolve.places_resolve(db, task(run, source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_TEXT))
    resolve.places_resolve(db, task(run, source=Source.REDNOTE, ref=NOTE, prompt=REDNOTE_OCR))
    db.commit()

    mention = db.scalars(select(PlaceMention)).one()
    assert mention.prompt_version == REDNOTE_OCR.version_key
    assert mention.why_go == "read off the image card"


def test_a_places_outage_is_transient_not_a_lost_task(db, run, monkeypatch):
    extraction(db, [yt_place()])

    def boom(*a, **k):
        raise PlacesError("places searchText returned 503")

    stub(monkeypatch, boom)

    with pytest.raises(TaskError) as e:
        resolve.places_resolve(db, task(run))
    assert e.value.code == ErrorCode.TRANSIENT


def test_a_missing_extraction_is_permanent(db, run, monkeypatch):
    counting(monkeypatch)

    with pytest.raises(TaskError) as e:
        resolve.places_resolve(db, task(run))
    assert e.value.code == ErrorCode.PERMANENT


def test_a_city_without_coordinates_cannot_be_geofenced(db, run, monkeypatch):
    """The bounding box is the defence against a garble resolving hundreds of km away."""
    extraction(db, [yt_place()])
    db.get(IngestRun, "run-1")
    from libs.db import City
    db.get(City, HELSINKI).lat = None
    db.commit()
    counting(monkeypatch)

    with pytest.raises(TaskError) as e:
        resolve.places_resolve(db, task(run))
    assert e.value.code == ErrorCode.PERMANENT
