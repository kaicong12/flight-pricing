# Local development. `make dev` is the one command: migrations, api, worker and the web app.
#
# Recipes are single shell commands with continuations rather than .ONESHELL, because macOS ships
# GNU Make 3.81 and .ONESHELL needs 3.82.

SHELL := /bin/bash
.DEFAULT_GOAL := help

API_PORT ?= 8000
WEB_PORT ?= 3000
# Prometheus's TSDB is the only copy of the metric history, so a teardown keeps it unless told not to.
KEEP_DATA ?= 1
BACKEND := tp_backend
CLIENT  := tp_client
ALEMBIC := uv run alembic -c libs/db/alembic.ini

.PHONY: help install dev api web worker migrate revision test lint build clean observability \
        observability-down

help:
	@echo "make dev        api + worker + web, one Ctrl-C stops all three"
	@echo "make api        backend only (migrate, then api + worker)"
	@echo "make web        web app only, against API_PORT"
	@echo "make worker     the ingestion worker on its own"
	@echo "make observability   prometheus + grafana, scraping the API's /metrics"
	@echo "make observability-down   stop them; add KEEP_DATA=0 to discard the metric history"
	@echo "make install    uv sync + npm ci"
	@echo "make migrate    alembic upgrade head"
	@echo "make revision m='what changed'   autogenerate a migration"
	@echo "make test       pytest"
	@echo "make lint       ruff + eslint + tsc"
	@echo "make build      production build of the web app"
	@echo ""
	@echo "ports: API_PORT=$(API_PORT) WEB_PORT=$(WEB_PORT)"

install:
	cd $(BACKEND) && uv sync
	cd $(CLIENT) && npm ci

# dev.sh owns the backend: it migrates, starts api + worker, and already kills that subtree from its
# own trap. So deliberately NO `set -m` here — children stay in this process group, which is what
# makes an interactive Ctrl-C reach dev.sh and `next dev` directly and lets each unwind itself. With
# `set -m` they get their own groups, the signal never arrives, and uvicorn survives holding the port.
# The trap covers the non-interactive case (`kill` on make), where no group signal arrives: it walks
# each child's descendants, because `npm` -> `next dev` -> `next-server` does not cascade and the
# grandchild would keep WEB_PORT bound. Polled rather than `wait -n`, which macOS's bash 3.2 lacks.
dev:
	@test -f .env || echo "!! no repo-root .env — GOOGLE_API_KEY and DATABASE_URL come from there"
	@test -d $(CLIENT)/node_modules || (echo "!! run 'make install' first" && exit 1)
	@echo "==> api http://localhost:$(API_PORT)   web http://localhost:$(WEB_PORT)"
	@pids=""; \
	killtree() { \
	    for child in $$(pgrep -P "$$1" 2>/dev/null); do killtree "$$child"; done; \
	    kill "$$1" 2>/dev/null || true; \
	}; \
	cleanup() { \
	    trap - INT TERM EXIT; \
	    for pid in $$pids; do killtree "$$pid"; done; \
	    wait 2>/dev/null || true; \
	}; \
	trap cleanup INT TERM EXIT; \
	PORT=$(API_PORT) ./dev.sh & pids="$$pids $$!"; \
	(cd $(CLIENT) && TP_API_URL=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(WEB_PORT)) & \
	    pids="$$pids $$!"; \
	while :; do \
	    for pid in $$pids; do \
	        kill -0 "$$pid" 2>/dev/null || exit 1; \
	    done; \
	    sleep 1; \
	done

api:
	PORT=$(API_PORT) ./dev.sh

web:
	cd $(CLIENT) && TP_API_URL=http://127.0.0.1:$(API_PORT) npm run dev -- --port $(WEB_PORT)

# Not --once: a throttle wait goes back to the queue via run_after, and drain() exits as soon as
# nothing is due.
worker:
	cd $(BACKEND) && uv run python -m tp_ingestions

# Separate from `make dev` so the one command you use all day never needs a docker daemon.
observability:
	@echo "==> Starting Observability stack..."
	docker compose -f docker-compose.observability.yml up -d
	@echo "==> Grafana  http://localhost:3001  (dashboard: API latency)"
	@echo "    Prometheus http://localhost:9090/targets"
	@echo "    Scrapes host.docker.internal:8000, so run 'make dev' or 'make api' alongside."

observability-down:
	@echo "==> Stopping Observability stack..."
	docker compose -f docker-compose.observability.yml down $(if $(filter 0,$(KEEP_DATA)),--volumes)
	@test "$(KEEP_DATA)" = "0" \
	    && echo "==> volumes removed, metric history discarded" \
	    || echo "==> volumes kept, metric history survives the next 'make observability'"

migrate:
	cd $(BACKEND) && $(ALEMBIC) upgrade head

revision:
	@test -n "$(m)" || (echo "usage: make revision m='add itinerary items'" && exit 1)
	cd $(BACKEND) && $(ALEMBIC) revision --autogenerate -m "$(m)"

test:
	cd $(BACKEND) && uv run pytest

lint:
	cd $(BACKEND) && uv run ruff check .
	cd $(CLIENT) && npx eslint src && npx tsc --noEmit

build:
	cd $(CLIENT) && npm run build

clean:
	rm -rf $(CLIENT)/.next
	find $(BACKEND) -name __pycache__ -prune -exec rm -rf {} +
