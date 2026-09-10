"""How the API logs, and the branches it logs about. See docs/observability.md."""

import json
import logging
from datetime import UTC, datetime

from conftest import HELSINKI, make_city, plan_body

from libs import logs
from libs.places import PlacesError


def record(level: int = logging.INFO, msg: str = "hello %s", args=("world",), exc_info=None):
    return logging.LogRecord("tp_api", level, __file__, 1, msg, args, exc_info)


def test_json_format_is_one_parseable_object_per_line():
    line = logs.JsonFormatter().format(record())

    payload = json.loads(line)
    assert payload == {"ts": payload["ts"], "level": "INFO", "logger": "tp_api",
                       "msg": "hello world"}
    assert payload["ts"].endswith("+00:00")
    assert "\n" not in line


def test_json_format_carries_a_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        line = logs.JsonFormatter().format(record(logging.ERROR, "it broke", (),
                                                  exc_info=sys.exc_info()))

    payload = json.loads(line)
    assert payload["level"] == "ERROR"
    assert "ValueError: boom" in payload["exc"]
    # A traceback is multi-line, and one log line must stay one log line.
    assert "\n" not in line


def test_install_picks_json_off_a_tty_and_text_on_one():
    logs.install(json_logs=True)
    assert isinstance(logging.getLogger().handlers[0].formatter, logs.JsonFormatter)

    logs.install(json_logs=False)
    formatter = logging.getLogger().handlers[0].formatter
    assert not isinstance(formatter, logs.JsonFormatter)
    assert formatter.format(record()).endswith("INFO    tp_api           hello world")


def test_a_cold_city_logs_the_run_it_queued(client, caplog):
    with caplog.at_level(logging.INFO, logger="tp_api"):
        r = client.post("/initiate-plan", json=plan_body())

    assert f"ingest=run:{r.json()['ingest']['run_id']}" in caplog.text
    assert HELSINKI in caplog.text


def test_a_warm_city_logs_that_it_queued_a_draft_instead(client, db, caplog):
    """The branch a response cannot show: whether anything is coming, or the draft is all there is."""
    make_city(db, last_ingested_at=datetime.now(UTC))

    with caplog.at_level(logging.INFO, logger="tp_api"):
        r = client.post("/initiate-plan", json=plan_body())

    assert r.json()["ingest"] is None, "the city was meant to be warm"
    assert "ingest=warm, draft queued" in caplog.text


def test_a_failed_places_lookup_is_logged_at_warning(client, lookup, caplog):
    def boom(place_id):
        raise PlacesError("quota exceeded")

    lookup["fn"] = boom

    with caplog.at_level(logging.WARNING, logger="tp_api"):
        r = client.post("/initiate-plan", json=plan_body())

    assert r.status_code == 502
    assert "initiate-plan places lookup failed" in caplog.text
    assert "quota exceeded" in caplog.text
    assert caplog.records[-1].levelno == logging.WARNING


def test_the_draft_endpoint_distinguishes_queued_from_already_running(client, caplog):
    trip_id = client.post("/initiate-plan", json=plan_body()).json()["trip_id"]

    with caplog.at_level(logging.INFO, logger="tp_api"):
        client.post(f"/trips/{trip_id}/draft")
        client.post(f"/trips/{trip_id}/draft")

    assert f"draft trip={trip_id[:8]} queued" in caplog.text
    assert f"draft trip={trip_id[:8]} not queued, one is already" in caplog.text
