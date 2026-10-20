"""Админка: детали синхронизации, просрочки, продления, заявки на срок, простой серверов и мощности кластера."""
from fastapi import APIRouter, BackgroundTasks

from app.api.deps import DB, AdminUser
from app.models import BookingExtension, TermRequest
from app.schemas.admin import ClusterCapacity, ExtensionOut, IdleServers, OverdueItem, TermApprove, TermRequestOut
from app.services import bookings, capacity, idle, overdue, sync_runs, term_requests

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


@router.get("/term-requests", response_model=list[TermRequestOut])
async def term_requests_list(_: AdminUser, session: DB) -> list[TermRequest]:
    return await term_requests.list_pending(session)


@router.post("/term-requests/{request_id}/approve", response_model=TermRequestOut)
async def term_request_approve(
    request_id: int, data: TermApprove, admin: AdminUser, session: DB, tasks: BackgroundTasks
) -> TermRequest:
    req = await term_requests.approve(session, admin, request_id, data.approved_return_at)
    tasks.add_task(bookings.push_to_insight)  # новый «Срок использования» ПК в Insight
    return req


@router.post("/term-requests/{request_id}/reject", response_model=TermRequestOut)
async def term_request_reject(request_id: int, admin: AdminUser, session: DB) -> TermRequest:
    return await term_requests.reject(session, admin, request_id)


@router.get("/idle", response_model=IdleServers)
async def idle_servers(_: AdminUser, session: DB) -> IdleServers:
    return await idle.list_idle(session)


@router.get("/cluster", response_model=ClusterCapacity)
async def cluster_capacity(_: AdminUser) -> ClusterCapacity:
    return await capacity.summary()
