# URL Shortener — DevOps Practical Assignment

A URL shortener with three parts: an API (create/redirect short links), Postgres (source of
truth), and Redis (cache). Built and deployed three ways — Docker Compose, Kubernetes (via Helm),
and with basic operational visibility/troubleshooting docs on top.

**Status:** Parts 1–3 complete and verified. One open item: imperative rollback commands
(`helm rollback` / `helm upgrade --set`) can desync `values.yaml` from the live cluster — see
Part 2's Design notes.

For the full decision log (why each choice was made, every bug found and how) see
`documentation.md`; for concept write-ups (cache-aside, base62, Docker/Kubernetes mechanics) see
`explanations.md`.

## Components
- **API** — Python + FastAPI.
- **PostgreSQL** — stores URL mappings (source of truth).
- **Redis** — caches lookups (cache-aside: check Redis → fall back to Postgres on a miss → write
  back to Redis).

## Endpoints

| Endpoint | Description |
|---|---|
| `POST /shorten` | Body: `{"url": "https://..."}` (max 2048 chars). Returns `{"short_code", "short_url"}`. |
| `GET /{short_code}` | Redirects (HTTP 302) to the original URL. 404 if not found. |
| `GET /health` | Status, dependencies, version, uptime, traffic counters. HTTP 503 when a dependency is down. |
| `GET /live` | Bare liveness check, no dependency calls. |
| `GET /dashboard` | Styled HTML view of `/health`, auto-refreshing every 3s — same data, easier to glance at. |

**`GET /health` response:**
```json
{
  "status": "ok",
  "postgres": true,
  "redis": true,
  "version": "v2",
  "uptime_seconds": 12.0,
  "metrics": {
    "shorten_requests": 2, "redirects": 3, "cache_hits": 2, "cache_misses": 1, "not_found": 1,
    "validation_errors": 0, "errors": 0
  }
}
```

Interactive docs (click-to-try, no `curl` needed) at `/docs` once the API is running.

> **Windows PowerShell:** `curl` there is aliased to `Invoke-WebRequest`, which doesn't understand
> real curl's flags (`-X`, `-H`, `-L`, `--json`) at all — not even `curl.exe` fixes it, since
> PowerShell's own argument-quoting for external commands mangles the JSON body differently than
> bash does. Skip `curl` entirely and use PowerShell's native equivalents instead:
> ```powershell
> Invoke-RestMethod -Uri "http://localhost:8000/health"
> Invoke-RestMethod -Uri "http://localhost:8000/shorten" -Method Post -ContentType "application/json" -Body '{"url":"https://example.com/x"}'
> Invoke-WebRequest -Uri "http://localhost:8000/1"   # follows the redirect automatically, no -L needed
> ```
> (Same commands work for both Part 1 and Part 2 — only the port ever changes, and it doesn't here.)
> Or simplest of all: use `/docs` above, no shell-specific syntax needed at all.

---

## Part 1 — Docker Compose

**Requirements:** Docker with Compose.

**How to run:**
```bash
cp .env.example .env
docker compose up --build
```
Waits for Postgres/Redis to report healthy before starting the API.

```bash
curl http://localhost:8000/health
curl http://localhost:8000/shorten --json '{"url":"https://example.com/x"}'
curl -L http://localhost:8000/1        # or open it directly in a browser
```

**How to stop:**
```bash
docker compose down          # keeps the Postgres data volume
docker compose down -v       # also wipes it (full reset)
```

**Verify persistence:** create a short URL → `docker compose down` (no `-v`) → `docker compose up -d`
→ the same code still resolves (data lives in the `postgres_data` volume, independent of the
containers).

**Design notes:**
- Postgres/Redis health is checked two ways: Compose's own `depends_on: condition: service_healthy`
  (gates when the API container *starts*) and the API's own internal retry loop on top (handles a
  dependency going down *after* startup, which Compose's check can't).
- Short codes are base62-encoded Postgres row ids, not random strings — deterministic, no collision
  handling needed, and no `short_code` column is stored (derived on every request).

---

## Part 2 — Kubernetes

**Requirements:** `kind`, `kubectl`, `helm`. Local cluster only — no cloud account needed.

**How to run:**
```bash
# one command (safe to rerun):
bash scripts/setup-k8s.sh

# or the manual steps it wraps:
kind create cluster --name url-short --config k8s/kind-cluster.yaml
docker build -t url-short-api:v1 ./api
kind load docker-image url-short-api:v1 --name url-short   # kind has its own image store — do this for every tag you use
helm install url-short ./helm/url-short
```
Credentials live in `helm/url-short/values.yaml` (default `changeme`, same placeholder pattern as
`.env.example`). For a real password: create a gitignored `helm/url-short/values.secret.yaml` and
pass `-f` it at install time, or `--set postgres.password=...`.

```bash
curl http://localhost:8000/health   # same address as Part 1 — see kind-cluster.yaml's port mapping
curl http://localhost:8000/shorten --json '{"url":"https://example.com/x"}'
curl -L http://localhost:8000/1
```

**How to stop:**
```bash
bash scripts/teardown-k8s.sh
# or manually:
helm uninstall url-short && kind delete cluster --name url-short
```

**Verify persistence/self-healing:**
```bash
kubectl delete pod -l app=postgres    # kills it outright
kubectl get pods -l app=postgres -w   # Deployment recreates it automatically
curl -L http://localhost:8000/<code>  # still resolves — survived via the PVC
```

**Rollout and rollback:**
```bash
helm upgrade url-short ./helm/url-short --set api.image.tag=v2
kubectl rollout status deployment/api

helm rollback url-short
kubectl rollout status deployment/api

helm history url-short        # revision history
helm get values url-short     # what's actually deployed right now
```

**Design notes:**
- **Helm**, not plain manifests/Kustomize (all three allowed). Built and fully tested as plain YAML
  first, then converted — `values.yaml` is now the single source of truth, so e.g. the Postgres
  Service name and the ConfigMap's `POSTGRES_HOST` can't drift apart (both read `.Values.postgres.name`).
- **Postgres**: Deployment + `strategy: Recreate` (not the default `RollingUpdate` — a `ReadWriteOnce`
  PVC can't be mounted by two pods at once) + PVC. Not a StatefulSet — single instance, no
  replication to justify one.
- **Redis**: plain Deployment, no PVC (losing cache data on restart is correct, not a gap), no auth
  (local-only scope).
- **API probes**: `readinessProbe` → `/health` (verified live: pulls the pod from the Service's
  routing pool during a real dependency outage). `livenessProbe` → `/live` instead, deliberately —
  tying liveness to dependency health would make Kubernetes restart a healthy pod during a Postgres
  outage, which can't fix Postgres and only adds churn.
- **Host access**: `NodePort`, not `port-forward` — persists independent of any open terminal.
- **Resources**: API/Postgres `100m–500m` CPU, `128–256Mi` memory; Redis lighter (`50m–200m`,
  `64–128Mi`) since it does less work per request. Local-demo starting points, not load-tested.
- **Known gap**: `helm upgrade --set` / `helm rollback` change the live release without touching
  `values.yaml` — same drift risk `kubectl rollout undo` had on plain manifests (recurred here too
  during testing). `helm get values` makes it detectable, doesn't prevent it. Not yet fixed.

---

## Part 3 — Operate and troubleshoot

The assignment asks for: enough visibility for an on-call engineer, plus a runbook for three
specific situations. Both below.

**How to check it:** `curl http://localhost:8000/health`, or open that URL (or `/dashboard` for a
styled, auto-refreshing view, or `/docs`) directly in a browser — status, per-dependency
reachability, version, uptime, and traffic counters (including `validation_errors`/`errors`, so a
bad-input spike is distinguishable from an actual server-side bug), all in one place. Plus logs
(`kubectl logs -l app=api` / `docker compose logs api`) for tracebacks on unhandled errors.

**Design notes:**
- `/health` returns HTTP `503` (not `200`) when degraded — probes and monitoring tools key off
  status codes, not JSON bodies, so this matters functionally, not just cosmetically.
- `/live` is separate from `/health` for the same liveness-vs-readiness reason as Part 2.
- **No Prometheus/Grafana** — a scraped-metrics endpoint is only useful once something's actually
  storing it over time, which means standing up that stack, which is explicitly more than this
  assignment asks for. In-`/health` counters give most of the practical value for zero extra
  infrastructure.

### Runbook

Each entry below was tested against a real, deliberately-triggered failure — not written from
assumption. See `documentation.md` for exactly how.

**1. The API is running but requests fail**
- Check `/health` first. `postgres`/`redis: false` → not this, go to #2.
- `/health` says `ok` but requests still fail → app-level bug. Check logs for a traceback.
- *Real example hit during development:* a 2049–2083 char URL passed Pydantic's validation but
  exceeded the DB column's 2048-char limit → raw `500` while `/health` stayed fully healthy. Log
  showed `StringDataRightTruncationError: value too long for type character varying(2048)`. Fixed
  by validating length at the API boundary.
- *Verify recovery:* retry the request, confirm success; confirm `/health` stayed `ok` throughout.

**2. The API cannot connect to PostgreSQL**
- `/health` → `"postgres": false` isolates it from Redis/app bugs.
- `kubectl get pods -l app=postgres` / `docker compose ps postgres` — is it actually up?
- `kubectl logs -l app=postgres` / `docker compose logs postgres` — what does it say?
- `kubectl get endpoints postgres` — does the Service have a live target?
- **Known gotcha:** Postgres only applies `POSTGRES_USER`/`PASSWORD` on the *first* init of an
  empty data dir — changing the Secret later without wiping the PVC leaves old credentials in
  place, and the API fails to authenticate even though the Secret "looks right."
- *Live-tested:* scaling Postgres to 0 reproduced this exactly — `/health` flipped to `degraded`
  within one check interval.
- *Verify recovery:* `/health` → `postgres: true`, then a real create→resolve cycle, not just the flag.

**3. A Kubernetes pod is running but receives no traffic**
- `kubectl get pods` — `READY: 0/1` (container running, probe failing) is the signature.
- `kubectl describe pod` — Events section names the specific probe failure.
- `kubectl get endpoints <service>` — confirms the pod's IP is genuinely missing from routing (this
  is Kubernetes correctly protecting traffic — the goal is finding *why* it's not ready).
- Root causes branch from there: dependency down (→ #2), crash-looping (`kubectl logs --previous`),
  misconfigured probe, or `OOMKilled`.
- *Live-tested, real captured event:* `Readiness probe failed: HTTP probe failed with statuscode: 503`
  — `kubectl get endpoints` showed no endpoints while unready, `RESTARTS` stayed `0` throughout
  (readiness and liveness reacting independently, as designed).
- *Verify recovery:* pod back to `1/1`, endpoint reappears, a request through the Service succeeds.

---

## Notes / assumptions / known limitations
- Short codes are sequential/guessable — fine for this scope, not for access control.
- No CI/CD — out of scope for the stated deliverables; would add a build+test GitHub Actions
  workflow as a stretch goal.
- No Prometheus/Grafana, no Helm-rollback/`values.yaml` sync tooling — both explained above, in
  Part 3 and Part 2's Design notes respectively.
- Redis has no auth — fine for local-only scope, not for a shared environment.
