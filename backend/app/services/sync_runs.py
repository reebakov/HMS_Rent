"""Страница «Синхронизация» в админке: журнал запусков, детали запуска, ручной запуск."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.models import SyncRun
from app.schemas.admin import SyncInfoOut, SyncRunOut
from app.services import runtime
from app.services.sync import run_sync


async def get_info(session: AsyncSession) -> SyncInfoOut:
    runs = (await session.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20))).all()
    return SyncInfoOut(
        mode=settings.insight_mode,
        jira_url=settings.jira_url,
        interval_sec=(await runtime.load(session)).insight_sync_interval_min * 60,
        writeback=runtime.current().insight_writeback,
        runs=[SyncRunOut.model_validate(r) for r in runs],
    )


async def get_run_details(session: AsyncSession, run_id: int) -> dict:
    run = await session.get(SyncRun, run_id)
    if run is None:
        raise NotFound("Запуск не найден")
    details = run.details or {}
    return {
        "id": run.id,
        "started_at": run.started_at,
        "updated": details.get("updated", []),
        "created": details.get("created", []),
        "archived": details.get("archived", []),
    }


async def run_now(session: AsyncSession) -> SyncRun:
    run = await run_sync(session)
    if run is None:
        raise Conflict("Синхронизация уже выполняется, попробуйте через минуту")
    return run
