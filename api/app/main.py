import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import check_redis, get_redis
from app.db import check_db, get_db, init_models
from app.models import URLMapping
from app.schemas import HealthResponse, ShortenRequest, ShortenResponse
from app.shortcode import decode, encode

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("url_shortener")

STARTUP_RETRY_ATTEMPTS = 10
STARTUP_RETRY_DELAY_SECONDS = 2
POSTGRES_INT_MAX = 2_147_483_647


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

    logger.info("Created short code %s -> %s", short_code, mapping.original_url)
    return ShortenResponse(short_code=short_code, short_url=short_url)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    postgres_ok = await check_db()
    redis_ok = await check_redis()
    overall = "ok" if postgres_ok and redis_ok else "degraded"
    return HealthResponse(status=overall, postgres=postgres_ok, redis=redis_ok)


@app.get("/{short_code}")
async def resolve_short_code(
    short_code: str,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> RedirectResponse:
    try:
        mapping_id = decode(short_code)
    except ValueError:
        raise HTTPException(status_code=404, detail="short code not found")

    if not 0 < mapping_id <= POSTGRES_INT_MAX:
        raise HTTPException(status_code=404, detail="short code not found")

    cache_key = f"url:{short_code}"
    cached_url = await redis.get(cache_key)
    if cached_url:
        logger.info("Cache hit for %s", short_code)
        return RedirectResponse(url=cached_url, status_code=302)

    result = await db.execute(select(URLMapping).where(URLMapping.id == mapping_id))
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=404, detail="short code not found")

    await redis.set(cache_key, mapping.original_url)
    logger.info("Cache miss for %s, populated cache from Postgres", short_code)
    return RedirectResponse(url=mapping.original_url, status_code=302)
