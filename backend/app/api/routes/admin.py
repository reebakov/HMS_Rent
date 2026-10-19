from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import DB, AdminUser
from app.core import clock
from app.models import Booking, Department, Pool, SyncRun
from app.schemas.admin import (
    ComputerAdminUpdate,
    ComputerHistoryOut,
    DepartmentUsage,
    EventOut,
    EventPage,
    InventoryPage,
    InventoryRow,
    PoolAssign,
    PoolAssignResult,
    PoolOut,
    PoolSave,
    StatsOut,
    SyncInfoOut,
    SyncRunOut,
)
from app.schemas.booking import BookingOut
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import computers, departments, inventory, pools, sync_runs

router = APIRouter(prefix="/admin", tags=["admin"])

POOL_FILTER = r"^(none|\d+)$"  # id пула или «none» — ПК вне пулов


# ---------- Сводка и инвентаризация ----------

@router.get("/stats", response_model=StatsOut)
async def stats(_: AdminUser, session: DB) -> StatsOut:
    return await inventory.get_stats(session)


@router.get("/inventory", response_model=InventoryPage)
async def inventory_list(
    _: AdminUser,
    session: DB,
    q: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    department_id: int | None = None,
    pool_id: str | None = Query(default=None, pattern=POOL_FILTER),
    issues_only: bool = False,
    include_archived: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> InventoryPage:
    items, total = await inventory.list_inventory(
        session, q=q, status=status, tier=tier, department_id=department_id, pool_id=pool_id,
        issues_only=issues_only, include_archived=include_archived, limit=limit, offset=offset,
    )
    return InventoryPage(items=items, total=total)


@router.get("/inventory/export")
async def inventory_export(
    _: AdminUser, session: DB, department_id: int | None = None,
    pool_id: str | None = Query(default=None, pattern=POOL_FILTER),
) -> Response:
    rows, _total = await inventory.list_inventory(session, department_id=department_id, pool_id=pool_id, limit=None)
    filename = f"inventory_{clock.today():%Y-%m-%d}.csv"
    return Response(
        content=inventory.inventory_csv(rows).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/computers/{computer_id}", response_model=ComputerHistoryOut)
async def computer_history(computer_id: int, _: AdminUser, session: DB) -> ComputerHistoryOut:
    return await computers.get_history(session, computer_id)


@router.patch("/computers/{computer_id}", response_model=InventoryRow)
async def update_computer(computer_id: int, data: ComputerAdminUpdate, admin: AdminUser, session: DB) -> InventoryRow:
    return await computers.update(session, admin, computer_id, data)


# ---------- Пулы выдачи ----------

@router.get("/pools", response_model=list[PoolOut])
async def list_pools(_: AdminUser, session: DB) -> list[PoolOut]:
    return await pools.list_pools(session)


@router.post("/pools", response_model=PoolOut, status_code=201)
async def create_pool(data: PoolSave, _: AdminUser, session: DB) -> Pool:
    return await pools.create_pool(session, data)


@router.patch("/pools/{pool_id}", response_model=PoolOut)
async def update_pool(pool_id: int, data: PoolSave, _: AdminUser, session: DB) -> PoolOut:
    return await pools.update_pool(session, pool_id, data)


@router.delete("/pools/{pool_id}", status_code=204)
async def delete_pool(pool_id: int, _: AdminUser, session: DB) -> None:
    await pools.delete_pool(session, pool_id)


@router.post("/pools/assign", response_model=PoolAssignResult)
async def assign_to_pool(data: PoolAssign, admin: AdminUser, session: DB) -> dict:
    return await pools.assign(session, admin, data.pool_id, computer_ids=data.computer_ids, names=data.names)


# ---------- Журнал ----------

@router.get("/bookings", response_model=list[BookingOut])
async def journal(
    _: AdminUser,
    session: DB,
    status: str | None = None,
    department_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
) -> list[Booking]:
    return await inventory.list_journal(
        session, status=status, department_id=department_id, date_from=date_from, date_to=date_to, q=q
    )


@router.get("/events", response_model=EventPage)
async def events(
    _: AdminUser, session: DB, 
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None
) -> EventPage:
    items, total = await inventory.list_events(
        session, limit=limit, offset=offset, 
        event_type=event_type, date_from=date_from, date_to=date_to, q=q
    )
    return EventPage(items=[EventOut.model_validate(e) for e in items], total=total)


# ---------- Отделы ----------

@router.get("/departments", response_model=list[DepartmentUsage])
async def departments_usage(_: AdminUser, session: DB) -> list[DepartmentUsage]:
    return await inventory.department_usage(session)


@router.post("/departments", response_model=DepartmentOut, status_code=201)
async def create_department(data: DepartmentCreate, _: AdminUser, session: DB) -> Department:
    return await departments.create(session, data)


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def update_department(department_id: int, data: DepartmentUpdate, _: AdminUser, session: DB) -> Department:
    return await departments.update(session, department_id, data)


# ---------- Синхронизация с Insight ----------

@router.get("/sync", response_model=SyncInfoOut)
async def sync_info(_: AdminUser, session: DB) -> SyncInfoOut:
    return await sync_runs.get_info(session)


@router.post("/sync", response_model=SyncRunOut)
async def sync_now(_: AdminUser, session: DB) -> SyncRun:
    return await sync_runs.run_now(session)
