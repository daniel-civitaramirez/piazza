"""Async SQLAlchemy engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from piazza.config.settings import settings

engine = create_async_engine(
    settings.supabase_db_url,
    poolclass=NullPool,
    connect_args=(
        {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
        if "asyncpg" in settings.supabase_db_url
        else {}
    ),
)

AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """Yield an async DB session."""
    async with AsyncSessionFactory() as session:
        yield session  # type: ignore[misc]
