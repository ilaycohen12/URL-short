from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

settings = get_settings()

# Give up connecting after 3s (asyncpg's default is 60s). When Postgres is unreachable on
# Kubernetes the connection attempt hangs rather than failing, so without this /health and every
# request that needs the database waited a full minute before failing.
DB_CONNECT_TIMEOUT_SECONDS = 3

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args={"timeout": DB_CONNECT_TIMEOUT_SECONDS},
)

# Errors that mean "Postgres can't be reached" (refused, DNS failure, timeout - all OSError -
# or SQLAlchemy's wrappers for connection failures). The API answers these with 503
# "temporarily unavailable"; anything else is a real bug and stays a 500.
DB_UNAVAILABLE_ERRORS = (OSError, OperationalError, InterfaceError)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_models() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure means "unhealthy", never an error
        return False
