# URL Shortener — DevOps Practical Assignment

A small URL shortener: an API that creates short links and redirects them, backed by
PostgreSQL (source of truth) and Redis (cache). The same app is deployed two independent
ways — Docker Compose (Part 1) and Kubernetes via Helm (Part 2) — with operational
visibility and a runbook on top (Part 3).

**Status:** Parts 1–3 complete and verified live.

| Path | What's there |
|---|---|
| `api/` | FastAPI app + Dockerfile |
| `docker-compose.yml`, `.env.example` | Part 1 |
| `helm/url-short/` | Part 2 Helm chart — `values.yaml` is the single source of truth |
| `k8s/kind-cluster.yaml` | Local kind cluster config (maps the API to `localhost:8000`) |
| `scripts/` | One-command Kubernetes setup / stop / teardown / drift check (`.sh` + PowerShell `.ps1`) |
| `documentation.md` | Decision log — why each choice was made, every bug found |
| `explanations.md` | Concept write-ups (cache-aside, base62, Helm, probes, …) |

```text
URL-short/
├── api/
│   ├── app/
│   │   ├── main.py            # FastAPI app: routes, metrics, exception handlers
│   │   ├── schemas.py         # request/response models + URL validation
│   │   ├── models.py          # SQLAlchemy table (url_mappings)
│   │   ├── db.py              # Postgres connection/session
│   │   ├── cache.py           # Redis client
│   │   ├── config.py          # settings from environment variables
│   │   ├── shortcode.py       # base62 encode/decode
│   │   └── dashboard.py       # /dashboard HTML page
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .dockerignore
├── helm/url-short/
│   ├── Chart.yaml
│   ├── values.yaml            # single source of truth for the Kubernetes deployment
│   └── templates/             # api / postgres / redis Deployments + Services,
│                              # postgres PVC, ConfigMap, Secret
├── k8s/
│   └── kind-cluster.yaml
├── scripts/
│   ├── setup-k8s.sh / .ps1       # create (or restart) the cluster + deploy
│   ├── stop-k8s.sh / .ps1        # stop the cluster, keep data
│   ├── check-drift.sh / .ps1     # does the cluster still match git?
│   └── teardown-k8s.sh / .ps1    # delete the cluster and all data
├── docker-compose.yml
├── .env.example
├── README.md
├── documentation.md
└── explanations.md
```

---

## Quick start

Compose and Kubernetes are **two independent ways to run the same app**. Both serve the API on `localhost:8000`, so **run only one at a time**.

**1. Start it** (pick one):

| | Docker Compose (Part 1) | Kubernetes (Part 2) |
|---|---|---|
| Needs | Docker with Compose | Docker, `kind`, `kubectl`, `helm` |
| Start — Linux / macOS / Git Bash | `cp .env.example .env` then `docker compose up --build` | `bash scripts/setup-k8s.sh` |
| Start — Windows PowerShell | `cp .env.example .env` then `docker compose up --build` | `.\scripts\setup-k8s.ps1` |
| Stop, keep data — Linux / macOS / Git Bash | `docker compose down` | `bash scripts/stop-k8s.sh` |
| Stop, keep data — Windows PowerShell | `docker compose down` | `.\scripts\stop-k8s.ps1` |
| Full reset (delete all data) — Linux / macOS / Git Bash | `docker compose down -v` | `bash scripts/teardown-k8s.sh` |
| Full reset (delete all data) — Windows PowerShell | `docker compose down -v` | `.\scripts\teardown-k8s.ps1` |

**2. Shorten a URL** — pick whichever is easiest:

*Option A — in the browser, no terminal needed:*
1. Open http://localhost:8000/docs
2. Click **`POST /shorten`** → **Try it out**
3. Replace the example URL in the body with your own, keeping the quotes:
   `{"url": "https://www.google.com"}`
4. Click **Execute** → scroll to **Response body**

*Option B — Windows PowerShell:*
```powershell
Invoke-RestMethod -Uri "http://localhost:8000/shorten" -Method Post -ContentType "application/json" -Body '{"url":"https://www.google.com"}'
```

*Option C — bash / Git Bash / macOS / Linux:*
```bash
curl http://localhost:8000/shorten --json '{"url":"https://www.google.com"}'
```

Either way you get back a short link:
```json
{"short_code": "1", "short_url": "http://localhost:8000/1"}
```
The URL must start with `http://` or `https://` — anything else is rejected with `422`.

**3. Open the `short_url`** (e.g. http://localhost:8000/1) in a browser → it redirects to the
original URL. (Use the browser's address bar for this, not the `/docs` page — see
[Using the API](#using-the-api).)

**4. Check it's healthy** → http://localhost:8000/health (JSON) or
http://localhost:8000/dashboard (same data, auto-refreshing). Explained in
[Part 3](#part-3--operate-and-troubleshoot).

---

## Using the API

| Endpoint | Description |
|---|---|
| `POST /shorten` | Body: `{"url": "https://..."}` (max 2048 chars). Returns `{"short_code", "short_url"}`. |
| `GET /{short_code}` | Redirects (HTTP 302) to the original URL. 404 if not found. |
| `GET /health` | Status, dependencies, version, uptime, traffic counters — see Part 3. |
| `GET /dashboard` | Browser view of `/health`, auto-refreshing — see Part 3. |
| `GET /live` | Bare liveness check, no dependency calls (used by Kubernetes). |
| `GET /docs` | Interactive, click-to-try API page (auto-generated by FastAPI). |

**Command-line examples** (same for Compose and Kubernetes; shortening is in the
[Quick start](#quick-start)):
```bash
# bash / Git Bash / macOS / Linux
curl -L http://localhost:8000/1          # follow a short link (-L = follow the redirect)
curl http://localhost:8000/health        # service status
```
```powershell
# Windows PowerShell
Invoke-WebRequest -Uri "http://localhost:8000/1"         # follows the redirect automatically
Invoke-RestMethod -Uri "http://localhost:8000/health"    # service status
```

**`/docs`** — the click-to-try page from the Quick start. Besides the response, it shows the
equivalent `curl` command and the status code for each call. It's generated from the code (routes +
Pydantic models), so it can't go out of date. Don't test redirects there — the browser blocks the
page from following a 302 to an external site ("Failed to fetch"); paste the short URL into the
address bar instead.

---

## Part 1 — Docker Compose

**Run:**
```bash
cp .env.example .env          # local config; .env is gitignored
docker compose up --build     # builds the API image, starts Postgres + Redis + API
```
The API waits for Postgres/Redis to report healthy before starting.

**Stop:**
```bash
docker compose down          # keeps the Postgres data volume
docker compose down -v       # also wipes it (full reset)
```

**Verify persistence:** create a short URL → `docker compose down` (no `-v`) →
`docker compose up -d` → the same code still resolves. The data lives in the `postgres_data`
volume, independent of the containers.

**Design notes:**
- Postgres/Redis health is checked two ways: Compose's `depends_on: condition: service_healthy`
  (gates when the API container *starts*) plus the API's own retry loop (handles a dependency
  going down *after* startup, which Compose's check can't).
- Short codes are base62-encoded Postgres row ids, not random strings — deterministic, no
  collision handling needed, and no `short_code` column is stored (derived on every request).
- **No deduplication, by choice:** shortening the same URL twice returns two different codes.
  Every `POST /shorten` is one plain `INSERT` — no lookup by URL, no unique constraint on
  `original_url` — and Redis only caches the redirect direction (code → URL). This is also how
  per-user shorteners behave (each link can later have its own owner/stats/expiry). To add dedup
  properly: a unique index on a hash of the URL (the raw URL is up to 2048 chars — too long to
  index well), `INSERT ... ON CONFLICT DO NOTHING` + read back the existing row (a plain "check,
  then insert" races under concurrent requests), and a decision on URL normalization
  (`https://a.com` vs `https://a.com/` vs `HTTPS://A.com`).

---

## Part 2 — Kubernetes

Local cluster only (`kind`) — no cloud account needed. Docker Desktop must be running.

**Run — one command** (safe to rerun: skips cluster creation if it exists, upgrades the release):
```bash
bash scripts/setup-k8s.sh          # Linux / macOS / Git Bash
.\scripts\setup-k8s.ps1            # Windows PowerShell
```
> **Windows:** don't run `bash scripts/setup-k8s.sh` from PowerShell. If WSL is installed, `bash`
> there is WSL's Linux bash, which can't see Windows-installed `kind`/`helm`/`kubectl`
> (`kind: command not found`). The `.ps1` wrappers call Git Bash explicitly to avoid this.

**Run — manual steps** (what the script wraps):
```bash
kind create cluster --name url-short --config k8s/kind-cluster.yaml
docker build -t url-short-api:v2 ./api                      # tag must match api.image.tag in values.yaml
kind load docker-image url-short-api:v2 --name url-short    # kind has its own image store — do this for every tag you use
helm install url-short ./helm/url-short
```

**Stop — two options** (same idea as Compose's `down` vs `down -v`):
```bash
# Stop, KEEP the data — short links are still there after the next setup-k8s:
bash scripts/stop-k8s.sh           # PowerShell: .\scripts\stop-k8s.ps1
# (manually: docker stop url-short-control-plane)

# Full reset, DELETE everything — the next setup-k8s starts from an empty database:
bash scripts/teardown-k8s.sh       # PowerShell: .\scripts\teardown-k8s.ps1
# (manually: helm uninstall url-short && kind delete cluster --name url-short)
```
A kind cluster is a single Docker container (`url-short-control-plane`), and the Postgres PVC is
stored on that container's disk. `stop` just stops the container, so the disk — and the data —
stays; `setup-k8s` detects the stopped cluster and starts it again instead of creating a new
one. `teardown` deletes the container, and the data goes with it. (Note: `helm uninstall` alone
also deletes the data — the PVC is part of the chart.)

**Credentials** live in `helm/url-short/values.yaml` (default `changeme`, same placeholder
pattern as `.env.example`). For a real password: create a gitignored
`helm/url-short/values.secret.yaml` and pass it with `-f` at install time, or
`--set postgres.password=...`.

**Verify persistence / self-healing:**
```bash
kubectl delete pod -l app=postgres    # kill it outright
kubectl get pods -l app=postgres -w   # the Deployment recreates it automatically
curl -L http://localhost:8000/<code>  # still resolves — the data survived on the PVC
```

**Rollout and rollback — through git:** `helm/url-short/values.yaml` in git is the source of
truth. Every change, including a rollback, is made in the file first; the cluster follows it.
```bash
# Roll out a new version:
#   edit helm/url-short/values.yaml (api.image.tag: v3), commit, then:
bash scripts/setup-k8s.sh                 # PowerShell: .\scripts\setup-k8s.ps1

# Roll back = undo the commit, then deploy again:
git revert <commit-that-bumped-the-tag>   # values.yaml goes back, as a new commit with a reason
bash scripts/setup-k8s.sh

# Check the cluster still matches git:
bash scripts/check-drift.sh               # PowerShell: .\scripts\check-drift.ps1
```
**Don't use `helm rollback` or `helm upgrade --set`** — they change the cluster without changing
the file, so git and the cluster silently disagree ("drift"), and the next deploy from git
re-releases the version you rolled back from.

**`check-drift`** catches it when something went around git anyway. Exit `0` = no drift,
`1` = drift (with the exact difference shown), `2` = couldn't check. Two checks:
1. **Helm's last deploy vs git** (`helm get manifest` vs `helm template`) — catches
   `helm rollback` and `helm upgrade --set`.
2. **Live cluster vs git** (`kubectl diff`) — catches changes that bypass Helm completely
   (`kubectl set image` / `edit` / `scale` / `rollout undo`), which check 1 can't see.

To fix drift, make git say what you want and run `setup-k8s` — it overwrites manual changes
(`--force-conflicts`, needed because Helm 4's server-side apply otherwise refuses to overwrite a
field someone changed with `kubectl`).

**Design notes:**
- **Helm**, not plain manifests/Kustomize (all three allowed). Built and fully tested as plain
  YAML first, then converted — `values.yaml` is now the single source of truth, so e.g. the
  Postgres Service name and the ConfigMap's `POSTGRES_HOST` can't drift apart (both read
  `.Values.postgres.name`).
- **Postgres**: Deployment + `strategy: Recreate` (not the default `RollingUpdate` — a
  `ReadWriteOnce` PVC can't be mounted by two pods at once) + PVC. Not a StatefulSet — single
  instance, no replication to justify one.
- **Redis**: plain Deployment, no PVC (losing cache data on restart is correct, not a gap), no
  auth (local-only scope).
- **API probes**: `readinessProbe` → `/health` (verified live: pulls the pod out of the Service's
  routing during a real dependency outage). `livenessProbe` → `/live` instead, deliberately —
  tying liveness to dependency health would make Kubernetes restart a healthy pod during a
  Postgres outage, which can't fix Postgres and only adds churn.
- **Host access**: `NodePort`, not `port-forward` — keeps working without an open terminal.
- **Resources**: API/Postgres `100m–500m` CPU, `128–256Mi` memory; Redis lighter (`50m–200m`,
  `64–128Mi`) since it does less work per request. Local-demo starting points, not load-tested.
- **Rollback drift — handled by process + detection, not enforcement**: rolling back through git
  (above) keeps the file and cluster in sync, and `check-drift` detects anything that went around
  it. Nothing *prevents* someone from running `helm rollback` by hand — enforcing that is what a
  GitOps controller (ArgoCD/Flux) adds: it watches the repo and reverts manual changes
  automatically. Out of scope for a local assignment. (Why not a script that rolls back and then
  copies the cluster's values into `values.yaml`? That makes the cluster the source of truth —
  backwards — and `helm get values` only returns overrides, not the full config.)

---

## Part 3 — Operate and troubleshoot

### Visibility

**`/health`** — one endpoint answers "is it up, what version, is it getting traffic":
```json
{
  "status": "ok",
  "postgres": true,
  "redis": true,
  "version": "v2",
  "uptime_seconds": 12.0,
  "metrics": {
    "shorten_requests": 6, "redirects": 6, "cache_hits": 2, "cache_misses": 4, "not_found": 1,
    "validation_errors": 0, "errors": 0
  }
}
```
- Returns HTTP **`503`** (not `200`) with `"status": "degraded"` when Postgres or Redis is
  unreachable. Probes and monitoring tools look at status codes, not JSON bodies, so this is what
  makes Kubernetes stop routing traffic to the pod.
- **`/live`** is a separate, dependency-free check used for the liveness probe — see Part 2's
  "API probes" note for why the two are split.

**`/dashboard`** — open http://localhost:8000/dashboard in a browser: the same data as `/health`,
styled and auto-refreshing every 3 seconds. Easier to glance at during an incident or a demo.

**Metrics** — what each counter means:

| Counter | Dashboard label | Counts |
|---|---|---|
| `shorten_requests` | Shortened | Successful `POST /shorten` — short links created |
| `redirects` | Redirects | Successful redirects (someone opened a valid short link) |
| `cache_hits` | Cache hits | Redirects answered from Redis — no Postgres query |
| `cache_misses` | Cache misses | Redirects not in Redis → looked up in Postgres, then written to Redis |
| `not_found` | Not found | Requests for a short code that doesn't exist (404) |
| `validation_errors` | Validation errors | Bad input rejected with `422` — the *client* sent something wrong |
| `errors` | Errors | Unhandled `500`s — a bug on *our* side; should always be 0 |

How to read them:
- **`redirects` = `cache_hits` + `cache_misses`**, always — every successful redirect is exactly
  one of the two. The first open of a link is a miss (Postgres, then cached); repeats are hits.
- A lookup that isn't in Postgres either counts as `not_found`, not as a miss.
- **`validation_errors` vs `errors`** tells you whose problem a spike is: clients sending bad
  data, or our code failing and needing someone on call.
- `not_found` often ticks up by itself from browsers requesting `/favicon.ico`.
- **Limits:** counters live in the API process's memory — they reset to 0 when the pod restarts
  (including after a rollout/rollback), and each replica counts separately (we run 1).

**Logs** — for the actual traceback behind an error:
`kubectl logs -l app=api` (Kubernetes) or `docker compose logs api` (Compose).

### Runbook

Each entry below was tested against a real, deliberately-triggered failure — not written from
assumption. See `documentation.md` for exactly how.

**1. The API is running but requests fail**
- Check `/health` first. `postgres`/`redis: false` → not this, go to #2.
- `/health` says `ok` but requests still fail → app-level bug. Check `errors` in the metrics, then
  the logs for a traceback.
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
- *Verify recovery:* `/health` → `postgres: true`, then a real create→resolve cycle, not just the
  flag.

**3. A Kubernetes pod is running but receives no traffic**
- `kubectl get pods` — `READY: 0/1` (container running, probe failing) is the signature.
- `kubectl describe pod` — the Events section names the specific probe failure.
- `kubectl get endpoints <service>` — confirms the pod's IP is genuinely missing from routing
  (this is Kubernetes correctly protecting traffic — the goal is finding *why* it's not ready).
- Root causes branch from there: dependency down (→ #2), crash-looping
  (`kubectl logs --previous`), misconfigured probe, or `OOMKilled`.
- *Live-tested, real captured event:*
  `Readiness probe failed: HTTP probe failed with statuscode: 503` — `kubectl get endpoints`
  showed no endpoints while unready, `RESTARTS` stayed `0` throughout (readiness and liveness
  reacting independently, as designed).
- *Verify recovery:* pod back to `1/1`, endpoint reappears, a request through the Service
  succeeds.

---

## Documentation

---

## Tools used

---

## Decisions

---

## Known limitations

- **Rollback drift is detected, not prevented** — rollbacks go through git and `check-drift`
  catches manual changes, but nothing blocks a manual `helm rollback`; that needs GitOps
  (ArgoCD/Flux). See Part 2's Design notes.
- **No deduplication** — the same URL shortened twice gets two codes; deliberate, see Part 1's
  Design notes.
- **Guessable short codes** — sequential by design; fine for this scope, not for access control.
- **In-memory metrics** — reset on restart, per replica (Part 3 → Metrics).
- **Redis has no auth** — fine for local-only scope, not for a shared environment.
- **No CI/CD** — out of scope for the stated deliverables; a build+test GitHub Actions workflow
  would be the next step.
