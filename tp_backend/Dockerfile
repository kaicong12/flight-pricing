# One image for both the API and the ingestion worker; the command picks which.
#
# REGISTRY is overridable because dockerd resolves base images using the *host* trust store, which a
# Dockerfile cannot patch — behind corporate TLS interception point it at an internal mirror. Nothing
# else needs an override: pypi.org verifies fine. Do not point uv at a different index either;
# uv.lock pins pypi.org URLs and --locked would reject the result.
ARG REGISTRY="docker.io"
FROM ${REGISTRY}/python:3.11-slim AS base

# Any *.crt dropped into certs/ is trusted. Needed at *runtime*, not to build: interception here is
# selective, so pypi.org verifies but webapi.rednote.com does not, and libs/http.py resolves it
# through truststore, which in a container means this bundle. Empty in git and a no-op when empty —
# these are the local proxy's roots, not the project's.
COPY certs/ /usr/local/share/ca-certificates/
RUN update-ca-certificates


FROM base AS builder

# Must match the uv that wrote uv.lock, or --locked fails on a lockfile it wants to rewrite.
ARG UV_VERSION=0.7.6
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# uv from the package index rather than COPY --from=ghcr.io/astral-sh/uv, which needs a second
# registry to be reachable.
RUN pip install --no-cache-dir "uv==${UV_VERSION}"

# Dependencies alone, so a source edit does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project


FROM base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
RUN useradd --create-home --uid 10001 app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app pyproject.toml uv.lock ./
COPY --chown=app:app libs libs
COPY --chown=app:app tp_api tp_api
COPY --chown=app:app tp_ingestions tp_ingestions

USER app
EXPOSE 8000

# Migrations are `alembic -c libs/db/alembic.ini upgrade head`; the ini is not at the project root.
CMD ["uvicorn", "tp_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
