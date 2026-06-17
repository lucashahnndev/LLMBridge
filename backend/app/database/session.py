from functools import lru_cache
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import get_settings


def _ensure_sqlite_database_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return

    database = url.database
    if not database or database == ":memory:":
        return

    Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_engine():
    settings = get_settings()
    _ensure_sqlite_database_parent(settings.database_url)
    return create_async_engine(settings.database_url, echo=False)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session
