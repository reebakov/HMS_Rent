from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict


@asynccontextmanager
async def conflict_on_integrity_error(session: AsyncSession, message: str) -> AsyncIterator[None]:
    """Нарушение уникального индекса внутри блока — это бизнес-конфликт (409), а не 500: откатываем и объясняем."""
    try:
        yield
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict(message) from exc
