from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.settings import settings


def init() -> tuple[AsyncEngine, async_sessionmaker]:
    engine = create_async_engine(
        settings.database_url_async,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_POOL_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    )
    sessionmaker = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    return engine, sessionmaker
