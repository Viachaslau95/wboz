import contextlib
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import init
from app.db.models import *  # noqa: F403

engine, Session = init()


@contextlib.asynccontextmanager
async def transaction(rollback: bool = False) -> AsyncIterator[AsyncSession]:
    async with Session() as session:
        async with session.begin():
            yield session
            if rollback:
                await session.rollback()
