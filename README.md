# URL Shortener — DevOps Practical Assignment

Status: **scaffolding stage** — repo structure set up, implementation in progress.

## Components
- **API** — Python + FastAPI. Creates short URLs, redirects visitors to the original URL.
- **PostgreSQL** — stores URL mappings (source of truth).
- **Redis** — caches URL lookups (cache-aside pattern).

## Endpoints (planned)
- `POST /shorten` — `{"url": "https://..."}` → `{"short_code": "...", "short_url": "..."}`
- `GET /{short_code}` — 302 redirect to the original URL
- `GET /health` — API + dependency (Postgres/Redis) health status

See `documentation.md` for the running decision log and `explanations.md` for concept write-ups.

## Setup instructions
_(to be filled in as Part 1 and Part 2 are built)_

## Runbook
_(to be filled in as part of Part 3)_
