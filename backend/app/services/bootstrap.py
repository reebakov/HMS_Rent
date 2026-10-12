"""Первичное наполнение: справочник отделов, пул по умолчанию и первая синхронизация при пустой базе."""
import logging

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Computer, Department, Pool
from app.services.sync import run_sync

log = logging.getLogger(__name__)

DEFAULT_POOL = "Общий пул"


async def bootstrap(session: AsyncSession) -> None:
    try:
        if not await session.scalar(select(func.count()).select_from(Department)):
            for name in settings.default_department_list:
                session.add(Department(name=name))
            log.info("Создан справочник отделов по умолчанию")
        if not await session.scalar(select(func.count()).select_from(Pool)):
            session.add(Pool(name=DEFAULT_POOL, description="ПК, которые видят все сотрудники", is_published=True))
            log.info("Создан пул «%s»", DEFAULT_POOL)
        await session.commit()
    except IntegrityError:  # параллельно стартующий процесс успел первым
        await session.rollback()

    if not await session.scalar(select(func.count()).select_from(Computer)):
        log.info("База пустая — запускаю первую синхронизацию с Insight (%s)", settings.insight_mode)
        await run_sync(session)

    in_pools = await session.scalar(select(func.count()).where(Computer.pool_id.is_not(None)))
    if settings.insight_mode == "mock" and not in_pools:
        # в демо сразу открываем все ПК; с настоящим Insight пулы наполняет админ
        pool_id = await session.scalar(select(Pool.id).where(Pool.name == DEFAULT_POOL))
        await session.execute(update(Computer).values(pool_id=pool_id))
        await session.commit()
