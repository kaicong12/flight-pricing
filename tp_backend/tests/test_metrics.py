"""GET /metrics: the request-duration histogram Prometheus scrapes."""

from prometheus_client import REGISTRY

COUNT = "http_request_duration_seconds_count"


def observations(route: str, method: str = "GET", status: str = "200") -> float:
    """How many requests the histogram has recorded for one label set; 0 if the series is absent."""
    value = REGISTRY.get_sample_value(COUNT, {"method": method, "route": route, "status": status})
    return value or 0.0


def test_metrics_serves_the_prometheus_exposition_format(client):
    client.get("/health")  # a labelled histogram emits no series until something is observed

    r = client.get("/metrics")

    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "# TYPE http_request_duration_seconds histogram" in r.text
    assert 'http_request_duration_seconds_bucket{le="0.005",method="GET",route="/health"' in r.text


def test_a_request_is_recorded_against_its_route(client):
    before = observations("/trips")

    client.get("/trips")

    assert observations("/trips") == before + 1


def test_the_route_label_is_the_template_not_the_path(client):
    """The cardinality guarantee: N trips must not become N series."""
    before = observations("/trips/{trip_id}", status="404")

    client.get("/trips/no-such-trip-a")
    client.get("/trips/no-such-trip-b")

    assert observations("/trips/{trip_id}", status="404") == before + 2
    assert observations("/trips/no-such-trip-a", status="404") == 0


def test_the_status_label_carries_the_response_code(client):
    before = observations("/trips/{trip_id}", status="404")

    client.get("/trips/nope")

    assert observations("/trips/{trip_id}", status="404") == before + 1
    assert observations("/trips/{trip_id}", status="200") == 0


def test_an_unmatched_path_is_not_recorded(client):
    """No route template means an unbounded label. 404s on junk paths must not mint series."""
    client.get("/there-is-no-such-endpoint")

    assert observations("/there-is-no-such-endpoint", status="404") == 0


def test_metrics_does_not_record_itself(client):
    before = observations("/metrics")

    client.get("/metrics")

    assert observations("/metrics") == before


def test_the_duration_is_observed_not_just_the_count(client):
    total = REGISTRY.get_sample_value("http_request_duration_seconds_sum",
                                      {"method": "GET", "route": "/health", "status": "200"}) or 0.0

    client.get("/health")

    after = REGISTRY.get_sample_value("http_request_duration_seconds_sum",
                                      {"method": "GET", "route": "/health", "status": "200"})
    assert after > total
