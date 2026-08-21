# Deploy

One `t4g.micro` (1 GiB RAM, 2 burstable vCPU, arm64) running `docker-compose.yml`: migrate + api +
one worker. Postgres is RDS, so there is no `db` service — `DATABASE_URL` comes from the environment.
`tp_client` is on Vercel, so there is no `web` service either; point Vercel's `TP_API_URL` at this
API's public URL.

## Build off the box

`docker compose build` on the instance is not an option. `next build` and `uv sync` both need more
than 1 GiB and will OOM. Build for arm64 on a laptop or in CI, push to a registry, and only ever
`pull` on the instance.

```bash
docker buildx build --platform linux/arm64 -t <registry>/tp-backend:<tag> --push ./tp_backend
```

On the instance, point compose at that tag and pull:

```bash
export BACKEND_IMAGE=<registry>/tp-backend:<tag>
docker compose pull
docker compose up -d
```

`migrate` runs `alembic -c libs/db/alembic.ini upgrade head` and exits; `api` and `worker` wait on it
completing successfully.

## Swap

2 GB of swap, as headroom for the odd spike rather than as working memory.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Memory budget

| | Steady state | `mem_limit` |
|---|---|---|
| api (uvicorn + SQLAlchemy pool) | ~150M | 256M |
| worker | ~200M | 320M |
| dockerd + containerd | ~80M | — |
| OS | ~120M | — |
| **Total** | **~550M** | |

Measured locally at idle, the Python processes are smaller than budgeted: worker ~75M, api ~75M. The
`mem_limit`s are the real test — see *Does a t4g.micro fit* below.

That leaves ~300M of a 1 GiB box free. The limits are the guard: they stop one service taking the
whole box down, and they are deliberately above steady state so a normal request spike does not get
OOM-killed.

## One worker container, not one per source

The claim SQL in `tp_ingestions/queue.py` selects any `status='pending' AND run_after <= now()` row
with no filter on `kind`, so a worker is source-agnostic. Splitting by source would mean adding kind
filtering to that query first, and it buys nothing: the work is quota-bound, not CPU-bound.

RedNote's 45s inter-call gap does not block anything either. A `Throttler` waits in-process only
below its `max_inline_wait` (10s for RedNote); anything longer raises `Throttled`, which the worker
turns into `queue.reschedule(...)` — the task goes back to `pending` with a future `run_after`, the
lease is released, and the attempt is **refunded**, because waiting for our own budget is not a
failure. A remote 429 is a different thing: that stays a `RATE_LIMITED` `TaskError` and does spend an
attempt. So the worker never sleeps holding a task, and YouTube tasks never starve behind RedNote.

**The budget is in Postgres, so it is shared.** `throttle_calls` holds per-domain call history, and
the check-and-spend runs under a per-domain advisory lock, so splitting the worker across hosts does
not hand each one its own allowance against a single real logged-in account. There is no state file
and no volume to migrate. The spend is committed on the throttler's own connection, never the
handler's: a task that rolls back must not refund a call the remote already served.

## Does a t4g.micro fit

RAM is not the thing to worry about; CPU credits and datacenter egress are.

Measured in a container at idle: **api 68 MiB / 256, worker 59 MiB / 320** — ~127 MiB of the box's
1 GiB. The open question is the peak during ingestion, not the floor.

**1. Prove RAM locally, for free.** Colima is arm64 and so are the images, so shrinking the VM to the
instance's shape is a faithful test. Build at full size first — `uv sync` needs more than 1 GiB, and
production never builds on the box:

```bash
docker compose build                       # at the current VM size
colima stop && colima start -c 2 -m 1      # same profile keeps its disk, so the image survives
export DATABASE_URL=...@host.docker.internal/trip_planner   # localhost is the container
docker compose up -d                       # run only, no --build
```

Then drive a full city ingestion from the UI and watch for an OOM kill:

```bash
docker stats --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'
docker inspect --format '{{.Name}} OOMKilled={{.State.OOMKilled}}' $(docker compose ps -aq)
```

Colima 0.10.1 has no swap flag while the instance has 2 GB of swap, so a pass at 1 GiB here is
stricter than the box. It does **not** test CPU: `-c 2` gives two full vCPUs, the instance gives two
burstable ones at a 10% baseline.

The worker's peak is `rednote.ocr` — up to `rednote_ocr_max_images` images held in memory and
base64'd for Gemini. If that fits in 320M, the box fits.

**2. CPU credits are the real limit, and only the box can tell you.** A `t4g.micro` sustains 10% of
2 vCPU and banks credits for bursts. Ingestion is mostly waiting on HTTP, so it should sit far below
baseline — but a throttle sleep still occupies the single-threaded worker, and `CPUCreditBalance`
trending down over hours is the signal to watch in CloudWatch, not instantaneous CPU.

**3. What will actually break first is not capacity.** `youtube-transcript-api` gets
`PoTokenRequired` from a datacenter IP, which maps to RATE_LIMITED and retries forever. That silently
removes YouTube — about 90% of candidates — leaving RedNote's handful. Test transcript fetching on the
box *before* judging anything else.

## To do

- A real `GET /health` endpoint. The `api` healthcheck currently probes `/openapi.json`, which only
  proves the process is serving, not that the database is reachable.

## Notes

- **Do not set `output: "standalone"` in `tp_client/next.config.ts`.** Vercel bundles for itself, and
  its Next 16.3.x packaging step fails with `ENOENT .next/next-server.js.nft.json` after a
  `next build` that succeeded. It was there for a `tp_client/Dockerfile` nothing ever built.
- `NODE_EXTRA_CA_CERTS` / `REQUESTS_CA_BUNDLE` are only needed behind corporate TLS interception.
  Not on EC2 — leave them unset.
- RDS: `sslmode=require` in `DATABASE_URL`.
- `api` and `worker` each hold their own SQLAlchemy pool, `db_pool_size + db_max_overflow` = 20
  connections each by default. Size RDS `max_connections` for both — a `db.t4g.micro` gives roughly
  80, so the defaults are close to half of it.
- If PgBouncer in transaction mode is ever introduced, `connect_args={"prepare_threshold": None}` is
  required (see the CLAUDE.md gotcha). Not needed connecting straight to RDS.
