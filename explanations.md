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

## Named volumes (Docker) vs. PersistentVolumeClaims (Kubernetes)

Containers are ephemeral by default — anything written inside them is lost when the container is
removed. A **named volume** in Docker Compose is storage that lives outside the container's
lifecycle, so Postgres's data directory survives a container restart/recreation. The Kubernetes
equivalent is a **PersistentVolumeClaim** (PVC) — a request for durable storage that a pod mounts,
independent of the pod's own lifecycle.
