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

from app.cache import check_redis, get_redis
from app.dashboard import DASHBOARD_HTML
from app.db import check_db, get_db, init_models
from app.models import URLMapping
from app.schemas import HealthResponse, Metrics, ShortenRequest, ShortenResponse
from app.shortcode import decode, encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("url_shortener")

STARTUP_RETRY_ATTEMPTS = 30
STARTUP_RETRY_DELAY_SECONDS = 2
POSTGRES_INT_MAX = 2_147_483_647
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
}


async def wait_for_dependencies() -> None:
    for attempt in range(1, STARTUP_RETRY_ATTEMPTS + 1):
        try:
            await init_models()
            if not await check_redis():
                raise RuntimeError("redis not reachable")
            logger.info("Dependencies ready (attempt %d)", attempt)
            return
        except Exception as exc:
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


app = FastAPI(title="URL Shortener", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    _metrics["validation_errors"] += 1
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    _metrics["errors"] += 1
    logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.post("/shorten", response_model=ShortenResponse)
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


@app.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    postgres_ok = await check_db()
    redis_ok = await check_redis()
    overall = "ok" if postgres_ok and redis_ok else "degraded"
    if not (postgres_ok and redis_ok):
        response.status_code = 503
    return HealthResponse(
        status=overall,
        postgres=postgres_ok,
        redis=redis_ok,
        version=APP_VERSION,
        uptime_seconds=round(time.monotonic() - START_TIME, 1),
        metrics=Metrics(**_metrics),
    )


@app.get("/live")
async def live() -> dict:
    return {"status": "alive"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return DASHBOARD_HTML


@app.get("/{short_code}")
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
    cached_url = await redis.get(cache_key)
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

    await redis.set(cache_key, mapping.original_url)
    _metrics["cache_misses"] += 1
    _metrics["redirects"] += 1
    logger.info("Cache miss for %s, populated cache from Postgres", short_code)
    return RedirectResponse(url=mapping.original_url, status_code=302)
