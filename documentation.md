# Documentation

Running log of what was done and why, split by category. Newest entries at the bottom of each section.

## Workflow

- **2026-09-23** — Assignment received from Shani (URL Shortener, DevOps practical). Estimate sent: ~13 hours.
- **2026-09-23** — Repo scaffolded as a monorepo at `URL-short/`, pushed to GitHub under `ilaycohen12/URL-short`.

## App

- **2026-09-23** — Decided on stack: **Python + FastAPI** for the API.
  - Why: built-in OpenAPI docs (covers the "document your endpoints" requirement), native async support (needed for non-blocking retries against Postgres/Redis on startup), small/readable codebase for the live demo/interview.
- **2026-09-23** — Endpoint design decided:
  - `POST /shorten` — body `{"url": "..."}`, inserts into Postgres, returns short code derived from the new row's id (base62-encoded), returns `{"short_code", "short_url"}`.
  - `GET /{short_code}` — checks Redis first (cache-aside), falls back to Postgres on miss, writes back to Redis, responds with HTTP 302 redirect to the original URL. 404 if not found anywhere.
  - `GET /health` — reports API status plus Postgres/Redis reachability. Used later for k8s probes and the Part 3 runbook.
  - Short code generation: base62-encode the Postgres auto-increment id, not random-string-with-collision-check — deterministic, no collision handling needed.

## Infra

- **2026-09-23** — Postgres and Redis will run as containers alongside the API in both setups (no managed/cloud DB, per assignment instructions).
  - Docker Compose: services on the same Docker network, addressed by service name; Postgres backed by a named volume for persistence.
  - Kubernetes: Postgres as Deployment/StatefulSet + PersistentVolumeClaim; Redis as a plain Deployment (cache — restart data loss is fine); both exposed via internal Services.

- **2026-09-23** — Created `api/app/` package skeleton (`main.py`, `config.py`, `db.py`, `cache.py`, `models.py`, `schemas.py`), each empty for now. One file per concern (routing/config/DB conn/Redis conn/DB model/API schema) instead of one script, so the Dockerfile can `COPY app/` and run `uvicorn app.main:app` — the standard FastAPI layout.

- **2026-09-23** — Added `api/requirements.txt`, pinned exact versions: fastapi, uvicorn[standard], sqlalchemy, asyncpg (async Postgres driver — matches our async endpoints), redis (async client), pydantic-settings (env var config loading). Pinned exact (not `>=`) for reproducibility on a clean machine.

- **2026-09-23** — Added `api/app/config.py` using `pydantic-settings`. Discrete `POSTGRES_*` vars (not a single `DATABASE_URL`) so they match the names the official Postgres image itself reads on init — one source of truth in `.env`. Default hosts (`postgres`, `redis`) are Docker Compose service names; will override to `localhost` via a local `.env` for the outside-Docker sanity check in step 9. `database_url`/`redis_url` computed via `@property`; `get_settings()` memoized with `@lru_cache` as a singleton.

- **2026-09-23** — Added `api/app/models.py`: single `url_mappings` table (`id`, `original_url`, `created_at`). Design refinement: no stored `short_code` column — it's derived (base62-encode/decode the `id`) on every request instead, so create is a single insert and lookup is a plain primary-key query. Avoids a two-step insert-then-update and an extra unique index.

- **2026-09-23** — Added `api/app/schemas.py`: `ShortenRequest` (validated `HttpUrl`), `ShortenResponse` (`short_code`/`short_url`), `HealthResponse` (`status` + per-dependency `postgres`/`redis` booleans). Kept separate from `models.py` on purpose — API contract vs. DB storage shape can diverge (e.g. `created_at` isn't exposed, `short_code` is never accepted on input).

- **2026-09-23** — Added `api/app/shortcode.py` (new file, not in the original 6-file plan — a standalone utility, so it got its own module): `encode(id)`/`decode(code)` base62 conversion. `decode` re-raises a clear `ValueError` on invalid characters so `main.py` can turn that into a 404 instead of a 500.

- **2026-09-23** — Added `api/app/db.py`: async SQLAlchemy engine (`pool_pre_ping=True`), `SessionLocal` factory, `init_models()` (create-table-if-not-exists — our migration strategy, single static table, no Alembic needed for this scope), `get_db()` FastAPI dependency (yields one session per request), `check_db()` (`SELECT 1`, bool result, for health checks + startup retry).
- **2026-09-23** — Added `api/app/cache.py`: shared `redis.asyncio` client built from config, `get_redis()` (returns the same pooled client — no per-request instance needed, unlike DB sessions), `check_redis()` (`PING`, bool result).

- **2026-09-23** — Added `api/app/main.py`, wiring all three endpoints:
  - `lifespan` startup hook retries `init_models()`/`check_redis()` up to 10x (2s apart) before accepting traffic — satisfies "API handles dependencies not ready yet." App fails loudly at startup if deps never come up, rather than serving 500s.
  - `POST /shorten` — no `db.refresh()` needed; `expire_on_commit=False` (db.py) + Postgres `RETURNING id` means `mapping.id` is already populated right after `commit()`. `short_url` built from `request.base_url`, not a hardcoded config value.
  - `GET /{short_code}` registered **after** `GET /health` — FastAPI matches routes in registration order, and a catch-all path param route registered first would swallow `/health` as if it were a short code. Route implements cache-aside: Redis check → Postgres fallback on miss → write-back to Redis → 302 redirect. Invalid short codes (`shortcode.decode` `ValueError`) → clean 404.
  - `GET /health` — checks both `check_db()`/`check_redis()`, returns `ok`/`degraded` plus per-dependency booleans.
  - Plain-text logging added on create/cache-hit/cache-miss (Part 3 visibility requirement); noted as a known simplification vs. structured JSON logging.

- **2026-09-23** — Added `api/Dockerfile` (`python:3.13-slim`, deps installed before app code copied for layer-cache efficiency, non-root `appuser`, `uvicorn` bound to `0.0.0.0` not `127.0.0.1` — required for reachability from outside the container) and `api/.dockerignore` (excludes `.venv/`, `.env`, caches from the build context).

- **2026-09-23** — Added `.env.example` at repo root (not `api/`) — Compose auto-loads a root-level `.env` for `${VAR}` substitution in `docker-compose.yml`. Same `POSTGRES_*`/`REDIS_*` names as `config.py`, hosts set to Compose service names (`postgres`/`redis`) since that's the correct default once Compose networking exists. Placeholder values only — real `.env` stays gitignored.

- **2026-09-23** — Added `docker-compose.yml` (repo root): postgres + redis + api on Compose's default network. postgres backed by named volume `postgres_data` for persistence. Both postgres/redis get healthchecks (`pg_isready`, `redis-cli ping`); api's `depends_on` uses `condition: service_healthy`, not plain `depends_on`, so Compose actually waits for readiness, not just container start — complements (doesn't replace) the app's own startup retry loop from Part 0, which covers dependencies going down *after* startup too. Only `api` is published to the host (`8000:8000`) — postgres/redis stay internal-only. All env vars sourced from root `.env` via `${VAR}` substitution, no hardcoded values, matching `.env.example`.

- **2026-09-23** — Verified persistence + startup ordering against the real Compose stack (not the earlier throwaway containers): `docker compose up --build -d` → created a short URL → `docker compose down` (removes containers + network, **keeps volumes**) → `docker compose up -d` again from nothing but the volume → the pre-teardown short code still resolved correctly. Proves the named volume, not container reuse, is what preserves Postgres data. Startup-ordering requirement also confirmed as a side effect: both `up` runs show `redis`/`postgres` reaching `Healthy` before `api` starts, confirming `condition: service_healthy` actually gates startup, not just declares intent.

- **2026-09-23** — **Part 1 complete.** Full clean-machine test: `docker compose down -v` (removes volume too, unlike the earlier persistence test) + `docker rmi url-short-api` (forces a true from-scratch build, no cached layer reuse) + `docker compose up --build -d`. Verified on the resulting instance: health check ok, previously-created code `1` now 404s (proves the wipe was real), fresh create→302-redirect flow works, both dependency containers report healthy. Every Part 1 assignment requirement confirmed working, not just present in the config.

## Bug-fixes

- **2026-09-23** (found during step 9 local sanity check) — Three real bugs caught before Part 1:
  1. `asyncpg==0.29.0` has no precompiled Windows wheel for Python 3.13 — pip tried to compile from C source and failed (missing MSVC Build Tools). Bumped to `asyncpg==0.30.0` (adds 3.13 wheels). Won't affect the Linux-based Docker image, but blocked local-outside-Docker testing.
  2. App startup looped forever with `greenlet` missing — SQLAlchemy's async engine needs `greenlet` internally, but plain `sqlalchemy==2.0.35` doesn't pull it in. Fixed by requiring the `[asyncio]` extra: `sqlalchemy[asyncio]==2.0.35`.
  3. **Real logic bug**: `GET /zzzzzz` (a validly-charactered but very large short code) returned `500` instead of `404`. `decode("zzzzzz")` = 32,590,299,105, which overflows Postgres's `INTEGER` column (max ~2.1B) — the DB rejected the query and the unhandled `DataError` surfaced as a 500. Fixed with an explicit bounds check (`0 < mapping_id <= 2_147_483_647`) in `main.py` before querying, so out-of-range codes get a clean 404 like any other not-found code.
- **2026-09-23** — Part 0 step 9 sanity check: ran the app locally (venv, not Docker) against throwaway `docker run` Postgres (port 5433) and Redis containers — not the eventual Compose stack, just enough to prove the app itself works end to end. Verified: `/health` (200, both deps true), full create→302-redirect flow, cache hit on second lookup, 404 on invalid/oversized codes, `/docs` loads. Throwaway containers removed afterward. Local `.env` (gitignored) left in place for future outside-Docker testing.

## GitOps

_(none yet)_
