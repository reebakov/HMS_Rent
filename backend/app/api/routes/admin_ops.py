"""Админка: детали синхронизации и просрочки."""
from fastapi import APIRouter

from app.api.deps import DB, AdminUser
from app.schemas.admin import OverdueItem
from app.services import overdue, sync_runs

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sync/runs/{run_id}")
async def sync_run_details(run_id: int, _: AdminUser, session: DB) -> dict:
    """Что изменилось в конкретном запуске: новые ПК, изменённые (поле: было → стало), ушедшие в архив."""
    return await sync_runs.get_run_details(session, run_id)


@router.get("/overdue", response_model=list[OverdueItem])
async def overdue_list(_: AdminUser, session: DB) -> list[OverdueItem]:
    return await overdue.list_items(session)
