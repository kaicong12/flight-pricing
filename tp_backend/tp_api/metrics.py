"""The one metric the API exposes: how long each request took. See docs/observability.md."""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest

PATH = "/metrics"

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Seconds spent serving a request.",
    ("method", "route", "status"),
)


def install(app: FastAPI) -> None:
    """Mount the scrape endpoint and the middleware that feeds it."""

    @app.get(PATH, include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.middleware("http")
    async def record(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path == PATH:
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started

        # Label with the route template, never the raw path; absent when nothing matched.
        route = request.scope.get("route")
        if route is not None:
            REQUEST_DURATION.labels(
                request.method, route.path, str(response.status_code)
            ).observe(elapsed)
        return response
