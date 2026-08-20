# Deploy

One `t4g.micro` (1 GiB RAM, 2 burstable vCPU, arm64) running `docker-compose.yml`. Postgres is RDS,
so there is no `db` service — `DATABASE_URL` comes from the environment.

## Build off the box

`docker compose build` on the instance is not an option. `next build` and `uv sync` both need more
than 1 GiB and will OOM. Build for arm64 on a laptop or in CI, push to a registry, and only ever
`pull` on the instance.

```bash
docker buildx build --platform linux/arm64 -t <registry>/tp-backend:<tag> --push ./tp_backend
docker buildx build --platform linux/arm64 -t <registry>/tp-web:<tag>     --push ./tp_client
```

On the instance, point compose at those tags and pull:

```bash
export BACKEND_IMAGE=<registry>/tp-backend:<tag> WEB_IMAGE=<registry>/tp-web:<tag>
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
| web (Next standalone) | ~150M | 256M |
| dockerd + containerd | ~80M | — |
| OS | ~120M | — |
| **Total** | **~700M** | |

That leaves ~300M of a 1 GiB box free. The limits are the guard: they stop one service taking the
whole box down, and they are deliberately above steady state so a normal request spike does not get
OOM-killed.

## One worker container, not one per source

The claim SQL in `tp_ingestions/queue.py` selects any `status='pending' AND run_after <= now()` row
with no filter on `kind`, so a worker is source-agnostic. Splitting by source would mean adding kind
filtering to that query first, and it buys nothing: the work is quota-bound, not CPU-bound.

RedNote's 45s inter-call gap does not block anything either. `rednote/throttle.py` waits in-process
only below `MAX_INLINE_WAIT` (10s); anything longer is raised as `RATE_LIMITED` with a `retry_after`,
which the worker turns into `queue.defer(...)` — the task goes back to `pending` with a future
`run_after` and the lease is released. So the worker never sleeps holding a task, and YouTube tasks
never starve behind RedNote.

**The throttle state file is per-host.** It is a file on the `rednote_throttle` named volume. Any
future split of the worker must share that volume — two hosts would each get their own 120-call
daily budget, against one real logged-in account.

## Cheaper variant

Put `web` on Vercel's free tier: drop the `web` service, point it at the API's public URL. The
instance falls to ~450M steady state and the Node build problem disappears entirely.

## To do

- **`output: "standalone"` must be added to `tp_client/next.config.ts`.** `tp_client/Dockerfile`
  copies `.next/standalone`, so the build fails without it.
- A real `GET /health` endpoint. The `api` healthcheck currently probes `/openapi.json`, which only
  proves the process is serving, not that the database is reachable.

## Notes

- `NODE_EXTRA_CA_CERTS` / `REQUESTS_CA_BUNDLE` are only needed behind corporate TLS interception.
  Not on EC2 — leave them unset.
- RDS: `sslmode=require` in `DATABASE_URL`.
- `api` and `worker` each hold their own SQLAlchemy pool, `db_pool_size + db_max_overflow` = 20
  connections each by default. Size RDS `max_connections` for both — a `db.t4g.micro` gives roughly
  80, so the defaults are close to half of it.
- If PgBouncer in transaction mode is ever introduced, `connect_args={"prepare_threshold": None}` is
  required (see the CLAUDE.md gotcha). Not needed connecting straight to RDS.
