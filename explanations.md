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

## Named volumes (Docker) vs. PersistentVolumeClaims (Kubernetes)

Containers are ephemeral by default — anything written inside them is lost when the container is
removed. A **named volume** in Docker Compose is storage that lives outside the container's
lifecycle, so Postgres's data directory survives a container restart/recreation. The Kubernetes
equivalent is a **PersistentVolumeClaim** (PVC) — a request for durable storage that a pod mounts,
independent of the pod's own lifecycle.
