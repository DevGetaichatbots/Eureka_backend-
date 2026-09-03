import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config import settings

# Normalize postgresql:// to postgresql+asyncpg:// if needed
raw_db_url = settings.DATABASE_URL
if raw_db_url.startswith("postgres://"):
    raw_db_url = raw_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+asyncpg://"):
    raw_db_url = raw_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

# Check if placeholder password is present
has_real_credentials = "[YOUR-PASSWORD]" not in raw_db_url and "[PASSWORD]" not in raw_db_url

if has_real_credentials:
    async_engine = create_async_engine(
        raw_db_url,
        echo=settings.DEBUG,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    AsyncSessionLocal = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
else:
    # Development fallback stub when direct DB password is not yet entered
    async_engine = None
    AsyncSessionLocal = None


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding an async database session.
    """
    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL contains placeholder credentials. "
            "Please update DATABASE_URL in .env with your actual Supabase PostgreSQL password."
        )

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
