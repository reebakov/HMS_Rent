"""Админка: детали синхронизации, просрочки и продления."""
from fastapi import APIRouter

from app.api.deps import DB, AdminUser
from app.models import BookingExtension
from app.schemas.admin import ExtensionOut, OverdueItem
from app.services import overdue, sync_runs

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sync/runs/{run_id}")
async def sync_run_details(run_id: int, _: AdminUser, session: DB) -> dict:
    """Что изменилось в конкретном запуске: новые ПК, изменённые (поле: было → стало), ушедшие в архив."""
    return await sync_runs.get_run_details(session, run_id)


@router.get("/overdue", response_model=list[OverdueItem])
async def overdue_list(_: AdminUser, session: DB) -> list[OverdueItem]:
    return await overdue.list_items(session)


@router.get("/extensions", response_model=list[ExtensionOut])
async def extensions_list(_: AdminUser, session: DB) -> list[BookingExtension]:
    return await overdue.list_extensions(session)


@router.post("/extensions/{extension_id}/ack", response_model=ExtensionOut)
async def extension_ack(extension_id: int, admin: AdminUser, session: DB) -> BookingExtension:
    return await overdue.acknowledge_extension(session, admin, extension_id)
