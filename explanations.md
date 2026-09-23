# Explanations

New technologies/concepts explained as we go, so you can look them up later without re-asking.

## Cache-aside pattern

A caching strategy where the app checks the cache first on read. On a miss, it reads the real
source of truth (Postgres), then writes the result into the cache so the next read is fast.
The cache never holds data the database doesn't also have — Postgres stays authoritative, Redis
is purely an accelerator. If Redis goes down entirely, reads should still work by falling straight
through to Postgres (slower, but correct).

## base62 encoding for short codes

Short codes need to be short, URL-safe, and unique. Instead of generating a random string and
checking for collisions, we encode the row's own Postgres auto-increment `id` (a plain integer)
into base62 — i.e. using the 62 characters `[a-zA-Z0-9]` instead of just `[0-9]`. Since the id is
already guaranteed unique by Postgres, the encoded code is guaranteed unique too, with no retry
logic needed. Example: id `125` → some short string like `"cb"`.

## Readiness vs. liveness probes (Kubernetes)

- **Liveness probe**: "is this process still alive, or should Kubernetes kill and restart it?"
  Failing liveness = pod gets restarted.
- **Readiness probe**: "is this pod ready to receive traffic right now?" Failing readiness = pod
  is temporarily pulled out of the Service's load-balancing pool (not restarted) until it passes
  again. This is what prevents traffic from hitting a pod that's up but still connecting to
  Postgres/Redis on startup.

## pydantic-settings (typed env var config)

A library that lets you declare app configuration as a typed Python class (a `BaseSettings`
subclass) instead of scattering `os.getenv("POSTGRES_USER", "default")` calls everywhere. Each
field automatically pulls from the matching environment variable (case-insensitive), gets type
validation, and can fall back to a local `.env` file if set. This is what makes the same code work
both inside Docker (env vars from `docker-compose.yml`) and locally (env vars from a `.env` file)
with no code changes.

## Docker Compose service-name DNS

Inside a Docker Compose network, each service can reach every other service by its **service
name** as if it were a hostname (Docker runs an internal DNS for this) — e.g. the API container
can connect to `postgres:5432` even though there's no machine literally named `postgres`. This
only works *inside* the Compose network; from the host machine you'd use `localhost` plus whatever
port was published.

## `@lru_cache` as a cheap singleton

`functools.lru_cache` normally memoizes a function's return value per set of arguments, to avoid
recomputing. Applied to a zero-argument function like `get_settings()`, it has a simpler effect:
the function only actually runs once per process, and every subsequent call returns the exact same
cached object — a lightweight way to get a singleton without writing a dedicated singleton class.

## FastAPI dependencies with `yield`

FastAPI lets a route declare a dependency (via `Depends(...)`) that runs before the route handler
and can also run cleanup code after it, by writing the dependency as a generator function: code
before `yield` runs first, the yielded value is handed to the route, and code after `yield` runs
once the request finishes — even if it raised an exception. `get_db()` uses this to open a DB
session, hand it to the route, then guarantee it's closed afterward, without every route having to
manage that manually.

## Connection pooling / `pool_pre_ping`

Opening a new database connection for every single query is expensive, so libraries keep a *pool*
of already-open connections and hand them out/reuse them. The risk: a pooled connection can go
stale (the DB restarted, a firewall dropped an idle connection) without the pool knowing. Setting
`pool_pre_ping=True` makes the pool test a connection with a cheap query before handing it to your
code, so a stale connection gets silently replaced instead of causing a confusing error mid-request.

## FastAPI `lifespan`

A function decorated as an async context manager (`@asynccontextmanager`) and passed to
`FastAPI(lifespan=...)`. Code before the `yield` runs once at app startup, before any request is
accepted; code after `yield` runs once at shutdown. Used here to retry Postgres/Redis connectivity
before the app starts serving traffic, instead of accepting requests it can't actually handle yet.

## Route registration order with path parameters

A route like `/{short_code}` matches almost any path segment, so if it's registered before a
specific route like `/health`, it "wins" the match first and the specific route becomes
unreachable. Frameworks generally match routes in registration order, so literal/specific paths
need to be declared before catch-all path-parameter routes.

## `RETURNING` clause (Postgres)

When you `INSERT` a row into a table with an auto-generated column (like our `id`), Postgres can
hand that generated value straight back in the same statement via `INSERT ... RETURNING id`,
instead of requiring a separate `SELECT` afterward to find out what id it assigned. SQLAlchemy's
async Postgres driver uses this automatically, which is why `mapping.id` is already available
right after `commit()` with no extra query needed.

## Precompiled wheels vs. building from source (Python packages)

Python packages with C extensions (like `asyncpg`) ship as prebuilt binary "wheels" for common
platform/Python-version combos, so `pip install` just downloads and uses one. If no matching
wheel exists (e.g. a very new Python version on Windows), pip falls back to compiling the C code
locally — which fails without the right compiler toolchain installed (here: "Microsoft Visual C++
14.0 or greater is required"). Fix was to bump to a newer package version that ships a wheel for
our Python version, not to install a compiler. This is a *local dev machine* problem specifically —
the Docker image runs Linux, where wheels exist for `asyncpg`, so it wasn't going to appear there.

## `greenlet` and SQLAlchemy's async engine

SQLAlchemy's async support is built on top of `greenlet`, a library that lets Python code switch
between different execution contexts cooperatively — it's what lets SQLAlchemy internally bridge
some sync-style code paths into the async world. It's a real, required dependency of async
SQLAlchemy, not optional — but plain `pip install sqlalchemy` doesn't pull it in; you need the
`sqlalchemy[asyncio]` extra. Without it, every async DB call fails at runtime with "the greenlet
library is required," even though the code looks completely correct.

## Integer overflow as an unvalidated boundary bug

Postgres's plain `INTEGER` type only holds values up to about 2.1 billion (2^31 - 1). Our short
codes are base62-encoded row ids, and a 6-character code (e.g. `"zzzzzz"`) decodes to a number
far bigger than that. Because nothing checked the decoded value's range before handing it to
Postgres, an oversized-but-validly-formatted code caused a raw database error instead of a normal
"not found" response — turning what should be a routine 404 into an unhandled 500. General lesson:
input validation isn't just "is this the right shape/characters," it's also "is this in the range
the next system downstream can actually accept" — and it should be checked *before* that system
sees it, not discovered via its error message.

## Docker layer caching

Each instruction in a Dockerfile creates a cached "layer." On a rebuild, Docker reuses layers
whose inputs haven't changed and only re-runs from the first changed layer onward. Copying
`requirements.txt` and running `pip install` *before* copying the rest of the app code means
editing app code doesn't invalidate the (often slow) dependency-install layer — only editing
`requirements.txt` does.

## `0.0.0.0` vs. `127.0.0.1` inside a container

`127.0.0.1` ("localhost") only accepts connections that originate from the same network
namespace — inside a container, that means only processes *inside that same container* can reach
it. Compose/Kubernetes reach a container's port from outside its network namespace, so the process
must bind to `0.0.0.0` (all network interfaces) to be reachable at all — even with ports otherwise
correctly published/mapped. `EXPOSE` in a Dockerfile is separate and purely documentation; it
doesn't publish anything by itself.

## Running containers as a non-root user

Containers run as `root` by default unless told otherwise. `root` inside a container isn't fully
isolated from the host in every configuration, and if an app is compromised (e.g. via a dependency
vulnerability), a root process inside the container has more potential damage radius than an
unprivileged one. Creating and switching to a dedicated user (`USER appuser`) is a standard
hardening step with no real downside for an app like this one.

## Docker Compose's automatic `.env` loading

Docker Compose automatically looks for a file literally named `.env` in the same directory as
`docker-compose.yml` and uses it to fill in `${VARIABLE_NAME}` placeholders anywhere in that file
— no explicit configuration needed to enable this. It does **not** read `.env.example` (that's
just a convention, not something Compose recognizes) — a user has to actually copy it to `.env`
first for values to take effect.

## Compose healthchecks + `depends_on: condition: service_healthy`

Plain `depends_on: [postgres]` in Compose only waits for the postgres *container process* to
start — not for Postgres itself to be ready to accept queries, which can take a few extra seconds
after the process starts. A `healthcheck:` block defines how Compose actually tests readiness
(e.g. running `pg_isready` repeatedly), and `depends_on: postgres: condition: service_healthy`
makes a dependent service wait for that healthcheck to pass, not just for the container to exist.
This only covers *startup* ordering though — it doesn't help if a dependency goes down again later
while the app is already running, which is why the app's own retry/health-check logic still
matters on top of this, not instead of it.

## `kind` (Kubernetes-in-Docker)

`kind` runs each Kubernetes cluster "node" as a Docker container rather than a VM, using Docker
itself as the substrate. This makes it fast and lightweight for local development/testing, since
it reuses your existing Docker install instead of needing a separate VM driver. The tradeoff:
because each node is a container, port mappings from the host into the cluster must be declared
in the cluster config **at creation time** — you can't add one to an already-running cluster the
way you can with a Compose file, since Docker itself doesn't support adding port publishes to a
running container.

## StorageClass and dynamic provisioning

A `StorageClass` tells Kubernetes *how* to create storage when a pod asks for it via a
PersistentVolumeClaim (PVC) — which underlying provisioner to use, what happens to the data when
the claim is deleted, etc. `kind` ships a default one (`standard`, backed by
`rancher.io/local-path`, which just uses a directory on the node's own disk) so a PVC can be
requested without us having to configure a storage backend ourselves — appropriate for local
development; a real cloud cluster would point this at actual block storage instead.

## Why `kind` needs `kind load docker-image`

Each `kind` node is a Docker container that runs its own container runtime (containerd) inside
itself — it's a separate image store from your host's Docker daemon, even though both are
technically "Docker" in some sense. `docker build` on your host only populates the host's image
store; the cluster can't see those images until they're explicitly copied in with
`kind load docker-image`. A real (non-local) cluster doesn't have this step at all — instead you
push the image to a container registry (Docker Hub, ECR, GCR, etc.) and the cluster pulls it from
there over the network; `kind load` exists purely to skip needing a registry for local development.

## `crictl`

A CLI that talks directly to a Kubernetes node's container runtime (via the CRI — Container
Runtime Interface), bypassing `kubectl` and the Kubernetes API server entirely. Useful for
answering low-level questions `kubectl` can't directly answer, like "is this image actually
present on this specific node" — the first thing to check when a pod is stuck in
`ImagePullBackOff`.

## `stringData` vs. `data` on a Kubernetes Secret

`data` requires every value to already be base64-encoded by you before it goes in the YAML —
error-prone to write and read by hand. `stringData` lets you write plain text in the manifest;
Kubernetes base64-encodes it automatically when the object is created, and it shows up under
`.data` from then on. Same end result stored in the cluster either way — `stringData` is purely a
convenience for authoring the manifest, not a different storage mechanism.

## Kubernetes Secrets are encoded, not encrypted (by default)

Base64 is a reversible *encoding*, not encryption — anyone who can read a Secret object via the
API (`kubectl get secret -o yaml`, same RBAC permission as reading a ConfigMap) can decode its
value in one command. The Secret/ConfigMap split exists for *architecture* — RBAC can restrict
Secret access separately, and it's the standard integration point for real secret-management tools
— not because Secrets are inherently encrypted at rest. A production cluster would layer on
encryption-at-rest for etcd and/or an external secrets manager on top of this.

## Deployment vs. StatefulSet for a single-instance database

StatefulSet is the Kubernetes-native choice for stateful, clustered workloads — it gives each pod
a stable, predictable identity (name, network address) that survives rescheduling, which matters
when replicas need to know about each other (e.g. a Postgres primary/replica set). For a single
instance with no replication, that machinery isn't buying anything — a plain Deployment with
`replicas: 1` behaves identically in practice for this case, with less to configure and explain.

## `strategy: Recreate` vs. `RollingUpdate`, and why it matters with RWO storage

A Deployment's default update strategy (`RollingUpdate`) starts the new pod *before* stopping the
old one, to avoid downtime. That only works if both pods *can* run simultaneously — but a
`ReadWriteOnce` PVC can only be mounted by one pod at a time. With the default strategy, an update
to a single-instance database backed by an RWO volume would hang indefinitely: the new pod can't
start (can't get the volume) and the old one never gets torn down to free it. `strategy: Recreate`
tells Kubernetes to stop the old pod first, then start the new one — the correct choice whenever a
workload can't have two live instances at once, at the cost of a brief gap in availability during
updates (acceptable for a single local Postgres instance; not for something meant to be
zero-downtime).

## `subPath` on a volume mount

Mounting a PersistentVolumeClaim directly onto Postgres's data directory can hit a known issue:
some storage provisioners leave content (like a `lost+found` folder) at the volume's root, which
`initdb` can refuse to initialize into. Setting `subPath: pgdata` mounts a subdirectory *within*
the volume as the actual mount point instead of the volume's root, sidestepping that class of
problem entirely — a small defensive habit, not something specific to any one provisioner.

## Why liveness probes shouldn't check downstream dependencies

A liveness probe failing tells Kubernetes to **kill and restart** the container; a readiness probe
failing tells it to **stop routing traffic to it**, without touching the container's lifecycle.
If a liveness probe checks something outside the app's own control — like "is Postgres
reachable" — then a database outage causes Kubernetes to repeatedly restart a perfectly healthy
API process, over and over, for a problem restarting it can never fix. That's strictly worse than
doing nothing: it adds restart churn (and potential `CrashLoopBackOff` noise) on top of an outage
that was already being handled correctly by the readiness probe alone. The fix is a liveness
endpoint that only proves the process itself is alive and responsive (a trivial handler with no
dependency calls), while the readiness endpoint is the one allowed to react to dependency health.
See also [[readiness-vs-liveness-probes-kubernetes]] for the base distinction.

## HTTP probes check status codes, not response bodies

A Kubernetes `httpGet` probe only looks at the HTTP status code (2xx–3xx = success, anything else
= failure) — it never parses the response body. An endpoint that always returns `200 OK` with a
JSON field like `"status": "degraded"` inside it will always look healthy to a probe, no matter
what the body says. Any health endpoint meant to drive a probe has to encode its result in the
status code itself (e.g. `503` when unhealthy), not just in the payload.

## Ways to reach a Service from outside the cluster

- **`ClusterIP`** (the default) — internal only, unreachable from outside the cluster at all. What
  we used for `postgres`/`redis`.
- **`NodePort`** — opens a fixed port (30000–32767 range) on every cluster node itself, forwarding
  to the Service. Persistent — works as long as the cluster's running, no matter what's happening
  in any particular terminal. What we used for `api`.
- **`LoadBalancer`** — asks the cloud provider to provision a real external load balancer with its
  own public IP. Doesn't really apply locally (`kind` has no cloud to ask), which is why it's not
  an option here.
- **`kubectl port-forward`** — not a Service type at all; a client-side tunnel that only exists
  while that specific `kubectl` command keeps running in a terminal. Great for quick debugging
  access to something that's normally `ClusterIP`-only; not something you'd point a real user or
  another system at.

## Kubernetes has no native "start this after that's healthy" between Deployments

Docker Compose's `depends_on: condition: service_healthy` can delay starting one container until
another passes its healthcheck. Kubernetes has no equivalent for ordering *between* separate
Deployments — all Deployments applied together start their pods simultaneously, with no built-in
concept of "wait for this other Deployment to be healthy first." The two real ways to handle a
dependency that isn't ready yet are: (1) the app's own retry logic, sized generously enough to
cover a worst-case cold start including image pulls, not just the warm-start case Compose users
might be used to — what we widened here — or (2) an `initContainer` on the dependent pod that
actively blocks (e.g. polling the dependency) before the main container even starts. We used
option 1, already having the retry logic from Part 0; an `initContainer` would be the more
idiomatic Kubernetes-native alternative for a more failure-sensitive real system.

## `kubectl rollout` — how rollout/rollback actually work

A Deployment keeps its **old ReplicaSets around** (scaled to 0, not deleted) after an update,
specifically so a rollback doesn't need to rebuild anything — `kubectl rollout undo` just scales
the previous ReplicaSet back up and the current one down. This is why rollback is fast and
reliable: it's not re-pulling an image or reapplying a manifest, it's reusing an object that was
already sitting there. `kubectl rollout history` lists each revision; `kubectl rollout undo
--to-revision=N` can target a specific one, not just "one back." The `CHANGE-CAUSE` column is only
populated if a `kubernetes.io/change-cause` annotation was set at the time of that revision —
without it, history is accurate but not self-explanatory.

## Declarative manifests vs. imperative commands — the drift risk

`kubectl apply -f file.yaml` is *declarative*: the file is the source of truth, and the cluster is
made to match it. `kubectl rollout undo`, `kubectl scale`, `kubectl set image`, etc. are
*imperative*: they change the live cluster directly, without touching any file. Mixing the two
(which is completely normal — `rollout undo` is the standard rollback command) creates a real risk:
after an imperative command, the cluster's actual state and the committed manifest can silently
disagree, and the next person to blindly `kubectl apply -f` the old manifest would undo your
rollback without realizing it. The fix is discipline, not tooling: after any imperative change you
intend to keep, update the manifest to match reality.

## Logs vs. metrics vs. a full monitoring stack

Three genuinely different things, often conflated: **logs** are discrete text events, read
chronologically, good for "what exactly happened at this moment." **Metrics** are numeric counters
accumulated over time (request counts, latencies) — more useful for "what's the overall shape of
traffic," but a raw metrics endpoint on its own is just a snapshot of current numbers, not a trend,
until something scrapes and stores it repeatedly. A **full monitoring stack** (Prometheus storing
those snapshots over time + Grafana visualizing them, often plus Alertmanager) is what turns
metrics into passive dashboards and alerts — genuinely useful, but real infrastructure to run and
maintain, not something to reach for by default. A lightweight middle ground for a small app: fold
a few in-memory counters directly into an existing health endpoint — gives a human-readable
snapshot of both state and rough activity in one place, with zero additional infrastructure.

## Reusing a mutable image tag means `kubectl apply` won't pick up new content alone

If you rebuild an image under the *same* tag (e.g. `v2` again) and reload it into the cluster, a
running Deployment's pod spec still just says `image: url-short-api:v2` — textually unchanged —
so `kubectl apply` sees no diff and triggers no rollout. The already-running pod keeps using
whatever it already had, even though the tag now technically points at different content. To force
it to actually pick up the new image, you need an explicit `kubectl rollout restart deployment/x`.
This is exactly why real deployments prefer unique, immutable tags per build (a commit SHA, a
build number) over reusing a mutable one like `latest` or a hand-picked version string during
active development — with a unique tag, changing the manifest's image reference is itself enough
to trigger a correct rollout, no separate restart command needed.

## Helm charts, concretely

A Helm chart is a templated set of Kubernetes manifests plus one `values.yaml` holding every
configurable value. `helm install`/`upgrade` renders the templates by substituting `.Values.x`
references and applies the result — functionally similar to `kubectl apply -f` on a folder, but
with real templating (a value used in five places only needs to be defined once) and built-in
release tracking (revision history, `helm rollback`, `helm get values` to see what's actually
deployed). The templates themselves stay close to plain Kubernetes YAML — mostly the same
Deployment/Service/ConfigMap shapes, just with hardcoded strings replaced by `{{ .Values.x }}`.

## Mutable image tags bite you again on a fresh cluster

Reusing a tag like `v1` across multiple cluster lifetimes means each *new* cluster starts with no
memory of what was `kind load`-ed into a previous one — the tag existing "in general" (on your
host's Docker, or in your own head) doesn't mean it exists on this specific node. Forgetting this
produces the exact same `ImagePullBackOff` as the first time this was documented, just from a
different trigger (a fresh cluster after switching to Helm, instead of a first-time deploy). The
practical takeaway: `kind load` isn't a one-time setup step, it's something to redo for every tag
you reference, every time the cluster itself is recreated.

## FastAPI/Starlette exception handlers

`@app.exception_handler(SomeExceptionType)` lets you intercept a specific exception type globally,
across every route, instead of wrapping each route in its own try/except. Starlette picks the most
specific registered handler for a given exception — so a handler for the base `Exception` class
only catches things with no more specific handler already registered (like `HTTPException`, which
FastAPI handles internally), meaning it's safe to add a catch-all without breaking existing 404s/
other intentional `HTTPException`s. One thing to watch: intercepting an exception yourself means
you're now responsible for anything the default handling used to do automatically — here, that
meant explicitly logging the traceback (`exc_info=True`) ourselves, since Starlette's own automatic
traceback logging only fires when an exception is left to propagate to *its* default handler, not
when a custom one catches it first.

## Named volumes (Docker) vs. PersistentVolumeClaims (Kubernetes)

Containers are ephemeral by default — anything written inside them is lost when the container is
removed. A **named volume** in Docker Compose is storage that lives outside the container's
lifecycle, so Postgres's data directory survives a container restart/recreation. The Kubernetes
equivalent is a **PersistentVolumeClaim** (PVC) — a request for durable storage that a pod mounts,
independent of the pod's own lifecycle.
