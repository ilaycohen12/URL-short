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

## Bug-fixes

_(none yet)_

## GitOps

_(none yet)_
