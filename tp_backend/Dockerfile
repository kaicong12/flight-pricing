# One image for both the API and the ingestion worker; the command picks which.
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies alone, so a source edit does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project


FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
RUN useradd --create-home --uid 10001 app \
    && install -d -o app -g app /state

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app pyproject.toml uv.lock ./
COPY --chown=app:app libs libs
COPY --chown=app:app tp_api tp_api
COPY --chown=app:app tp_ingestions tp_ingestions

USER app
EXPOSE 8000

# Migrations are `alembic -c libs/db/alembic.ini upgrade head`; the ini is not at the project root.
CMD ["uvicorn", "tp_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
