"""Админка: детали синхронизации и просрочки."""
from datetime import date, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DB, AdminUser
from app.models import SyncRun
from app.services import overdue

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/sync/runs/{run_id}")
async def sync_run_details(run_id: int, _: AdminUser, session: DB) -> dict:
    """Что изменилось в конкретном запуске: новые ПК, изменённые (поле: было → стало), ушедшие в архив."""
    run = await session.get(SyncRun, run_id)
    if run is None:
        raise HTTPException(404, "Запуск не найден")
    details = run.details or {}
    return {
        "id": run.id,
        "started_at": run.started_at,
        "updated": details.get("updated", []),
        "created": details.get("created", []),
        "archived": details.get("archived", []),
    }


class OverdueItem(BaseModel):
    kind: str  # pc / vm
    id: int  # booking_id или vm_id
    order_number: int | None
    name: str
    department: str
    requester_name: str
    requester_nick: str
    email: str | None
    taken_at: datetime | None
    due: date
    days: int


@router.get("/overdue", response_model=list[OverdueItem])
async def overdue_list(_: AdminUser, session: DB) -> list[OverdueItem]:
    bookings, vms = await overdue.list_overdue(session)
    items = [
        OverdueItem(kind="pc", id=b.id, order_number=b.order_number, name=b.computer.name, department=b.department.name,
                    requester_name=b.requester_name, requester_nick=b.requester_nick, email=b.user.email,
                    taken_at=b.booked_at, due=b.expected_return_at, days=overdue.days_overdue(b.expected_return_at))
        for b in bookings
    ] + [
        OverdueItem(kind="vm", id=v.id, order_number=v.order_number, name=v.name, department=v.department.name,
                    requester_name=v.requester_name, requester_nick=v.requester_nick, email=v.user.email,
                    taken_at=v.ready_at or v.created_at, due=v.expected_return_at,
                    days=overdue.days_overdue(v.expected_return_at))
        for v in vms
    ]
    return sorted(items, key=lambda i: -i.days)
