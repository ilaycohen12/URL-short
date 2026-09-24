import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import cache_get, cache_set, check_redis, get_redis
from app.dashboard import DASHBOARD_HTML
from app.db import DB_UNAVAILABLE_ERRORS, check_db, count_links, get_db, init_models
from app.models import URLMapping
from app.schemas import HealthResponse, Metrics, ShortenRequest, ShortenResponse
from app.shortcode import decode, encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("url_shortener")

STARTUP_RETRY_ATTEMPTS = 30
STARTUP_RETRY_DELAY_SECONDS = 2
POSTGRES_INT_MAX = 2_147_483_647
# Each /health dependency check must answer within this, below the readiness probe's 3s
# timeoutSeconds - so the probe always gets a real 503 instead of timing out itself.
HEALTH_CHECK_TIMEOUT_SECONDS = 2
APP_VERSION = "v2"

START_TIME = time.monotonic()
_metrics = {
    "shorten_requests": 0,
    "redirects": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "not_found": 0,
    "validation_errors": 0,
    "errors": 0,
    "db_unavailable": 0,
}


async def wait_for_dependencies() -> None:
    for attempt in range(1, STARTUP_RETRY_ATTEMPTS + 1):
        try:
            await init_models()
            logger.info("Dependencies ready (attempt %d)", attempt)
            # Redis is optional (cache only): don't block startup on it, or an API restart during
            # a Redis outage would never come up.
            if not await check_redis():
                logger.warning("Redis not reachable at startup - serving from Postgres until it is")
            return
        except Exception as exc:  # noqa: BLE001 - keep retrying on any startup error
            logger.warning(
                "Dependencies not ready yet (attempt %d/%d): %s",
                attempt,
                STARTUP_RETRY_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(STARTUP_RETRY_DELAY_SECONDS)
    raise RuntimeError("Dependencies did not become ready in time")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await wait_for_dependencies()
    yield


# Everything below up to the routes is documentation metadata for /docs
# (it ends up in /openapi.json) - it doesn't change how any endpoint behaves.
API_DESCRIPTION = """
Create short links and redirect them to the original URL.

**How to use:** `POST /shorten` with a URL → you get a `short_url` back →
open it in a browser and you're redirected.

PostgreSQL stores the links (source of truth); Redis caches lookups.
Service status: `/health` (JSON) or `/dashboard` (browser view).

**Note:** don't test `GET /{short_code}` from this page — the browser blocks it
from following a redirect to another site ("Failed to fetch"). Paste the
`short_url` into the address bar instead.
"""

OPENAPI_TAGS = [
    {"name": "Short links", "description": "Create a short link and resolve it."},
    {"name": "Operations", "description": "Status checks for operators and Kubernetes probes."},
]

app = FastAPI(
    title="URL Shortener",
    version=APP_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
    redoc_url=None,  # /docs is the one docs page; the built-in /redoc was dropped
    # Hide the "Schemas" section at the bottom of /docs - the same models are
    # already shown inline under each endpoint.
    swagger_ui_parameters={"defaultModelsExpandDepth": -1},
)

DB_UNAVAILABLE_RESPONSE = {
    503: {
        "description": "Postgres is temporarily unreachable - retry later.",
        "content": {"application/json": {"example": {"detail": "Database temporarily unavailable"}}},
    }
}

NOT_FOUND_RESPONSE = {
    404: {
        "description": "No short link with this code exists.",
        "content": {"application/json": {"example": {"detail": "short code not found"}}},
    }
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _metrics["validation_errors"] += 1
    return await request_validation_exception_handler(request, exc)


async def db_unavailable_handler(request: Request, exc: Exception):
    # Postgres unreachable: a temporary outage, not a bug in our code - 503 tells clients to retry
    # later and keeps these out of the `errors` counter (which should mean "our bug").
    _metrics["db_unavailable"] += 1
    logger.warning("Postgres unavailable on %s %s: %r", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})


for _exc_type in DB_UNAVAILABLE_ERRORS:
    app.add_exception_handler(_exc_type, db_unavailable_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _metrics["errors"] += 1
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.post(
    "/shorten",
    response_model=ShortenResponse,
    tags=["Short links"],
    summary="Create a short link",
    description="Stores the URL and returns its short code. Shortening the same URL twice "
    "returns two different codes (no deduplication, by design).",
    responses={
        422: {"description": "Invalid input — not a valid http(s) URL, or longer than 2048 characters."},
        **DB_UNAVAILABLE_RESPONSE,
    },
)
async def shorten_url(
    payload: ShortenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ShortenResponse:
    mapping = URLMapping(original_url=str(payload.url))
    db.add(mapping)
    await db.commit()

    short_code = encode(mapping.id)
    short_url = str(request.base_url) + short_code

    _metrics["shorten_requests"] += 1
    logger.info("Created short code %s -> %s", short_code, mapping.original_url)
    return ShortenResponse(short_code=short_code, short_url=short_url)


async def _links_stored() -> int | None:
    """Stored-link count for /health, or None if Postgres can't answer in time."""
    try:
        return await asyncio.wait_for(count_links(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
    except (TimeoutError, *DB_UNAVAILABLE_ERRORS):
        return None


async def _check_within_timeout(check) -> bool:
    """A dependency check that takes too long counts as 'down' - /health must always answer fast."""
    try:
        return await asyncio.wait_for(check(), timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
    except TimeoutError:
        return False


@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Operations"],
    summary="Service status, dependencies and traffic counters",
    description="Reports whether Postgres and Redis are reachable, the running version, uptime "
    "and in-memory traffic counters. Used as the Kubernetes readiness probe. If only Redis is down, "
    "returns 200 with `status: degraded` — requests are still served (from Postgres, without cache).",
    responses={503: {"description": "Postgres is unreachable — the API can't serve requests (`status: degraded`)."}},
)
async def health(response: Response) -> HealthResponse:
    postgres_ok, redis_ok = await asyncio.gather(_check_within_timeout(check_db), _check_within_timeout(check_redis))
    overall = "ok" if postgres_ok and redis_ok else "degraded"
    # 503 only when the API really can't work. Redis is just a cache: without it requests are
    # served from Postgres, so the pod must stay in the readiness pool (a cache outage must not
    # become a full outage). `redis: false` + "degraded" still tells on-call something is wrong.
    if not postgres_ok:
        response.status_code = 503
    return HealthResponse(
        status=overall,
        postgres=postgres_ok,
        redis=redis_ok,
        version=APP_VERSION,
        uptime_seconds=round(time.monotonic() - START_TIME, 1),
        links_stored=await _links_stored() if postgres_ok else None,
        metrics=Metrics(**_metrics),
    )


@app.get(
    "/live",
    tags=["Operations"],
    summary="Liveness check",
    description="Always returns `alive` if the process is running — no dependency checks. "
    "Used as the Kubernetes liveness probe.",
)
async def live() -> dict:
    return {"status": "alive"}


# A web page for people, not an API call - hidden from /docs, still served normally.
@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard() -> str:
    return DASHBOARD_HTML


@app.get(
    "/{short_code}",
    response_class=RedirectResponse,
    status_code=302,
    tags=["Short links"],
    summary="Redirect to the original URL",
    description="Looks the code up (Redis first, then Postgres) and redirects to the original URL.",
    responses={
        302: {"description": "Redirect to the original URL (see the `Location` header)."},
        **NOT_FOUND_RESPONSE,
        **DB_UNAVAILABLE_RESPONSE,
    },
)
async def resolve_short_code(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> RedirectResponse:
    try:
        mapping_id = decode(short_code)
    except ValueError:
        _metrics["not_found"] += 1
        raise HTTPException(status_code=404, detail="short code not found")

    if not 0 < mapping_id <= POSTGRES_INT_MAX:
        _metrics["not_found"] += 1
        raise HTTPException(status_code=404, detail="short code not found")

    cache_key = f"url:{short_code}"
    cached_url = await cache_get(redis, cache_key)
    if cached_url:
        _metrics["cache_hits"] += 1
        _metrics["redirects"] += 1
        logger.info("Cache hit for %s", short_code)
        return RedirectResponse(url=cached_url, status_code=302)

    result = await db.execute(select(URLMapping).where(URLMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if mapping is None:
        _metrics["not_found"] += 1
        raise HTTPException(status_code=404, detail="short code not found")

    await cache_set(redis, cache_key, mapping.original_url)
    _metrics["cache_misses"] += 1
    _metrics["redirects"] += 1
    logger.info("Cache miss for %s, populated cache from Postgres", short_code)
    return RedirectResponse(url=mapping.original_url, status_code=302)
