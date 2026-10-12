from datetime import date

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.schemas.admin import EventPage

from app.api.deps import DB, AdminUser
from app.core.config import settings
from app.models import AssetEvent, Booking, Computer, Department, EventType, Pool, SyncRun
from app.schemas.admin import (
    ComputerAdminUpdate, ComputerHistoryOut, DepartmentUsage, EventOut, InventoryPage, InventoryRow,
    PoolAssign, PoolAssignResult, PoolOut, PoolSave, StatsOut, SyncInfoOut, SyncRunOut,
)
from app.schemas.booking import BookingOut
from app.schemas.department import DepartmentCreate, DepartmentOut, DepartmentUpdate
from app.services import inventory, pools
from app.services.events import add_event
from app.services.sync import run_sync
from app.services.tiering import classify

router = APIRouter(prefix="/admin", tags=["admin"])


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
    pool_id: str | None = None,
    issues_only: bool = False,
    include_archived: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> InventoryPage:
    items, total = await inventory.list_inventory(
        session, q=q, status=status, tier=tier, department_id=department_id, pool_id=pool_id,
        issues_only=issues_only, include_archived=include_archived, limit=min(max(limit, 1), 500), offset=offset,
    )
    return InventoryPage(items=items, total=total)


@router.get("/inventory/export")
async def inventory_export(
    _: AdminUser, session: DB, department_id: int | None = None, pool_id: str | None = None
) -> Response:
    rows, _total = await inventory.list_inventory(session, department_id=department_id, pool_id=pool_id, limit=None)
    filename = f"inventory_{date.today():%Y-%m-%d}.csv"
    return Response(
        content=inventory.inventory_csv(rows).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/computers/{computer_id}", response_model=ComputerHistoryOut)
async def computer_history(computer_id: int, _: AdminUser, session: DB) -> ComputerHistoryOut:
    comp = await session.get(Computer, computer_id)
    if comp is None:
        raise HTTPException(404, "Компьютер не найден")
    bookings = (await session.scalars(
        select(Booking).where(Booking.computer_id == comp.id).order_by(Booking.booked_at.desc())
    )).unique().all()
    active = next((b for b in bookings if b.status == "active"), None)
    events = await inventory.list_events(session, computer_id=comp.id, limit=200)
    return ComputerHistoryOut(
        computer=inventory._row(comp, active),
        attributes=comp.attributes or {},
        bookings=[BookingOut.model_validate(b) for b in bookings],
        events=[EventOut.model_validate(e) for e in events],
    )


@router.patch("/computers/{computer_id}", response_model=InventoryRow)
async def update_computer(computer_id: int, data: ComputerAdminUpdate, admin: AdminUser, session: DB) -> InventoryRow:
    comp = await session.get(Computer, computer_id)
    if comp is None:
        raise HTTPException(404, "Компьютер не найден")
    changes = data.model_dump(exclude_unset=True)
    if "tier_override" in changes:
        comp.tier_override = changes["tier_override"].value if changes["tier_override"] else None
        comp.tier = comp.tier_override or classify(is_virtual=comp.is_virtual, ram_gb=comp.ram_gb, gpu=comp.gpu)
    if "note" in changes:
        comp.note = changes["note"] or None
    add_event(
        session, computer_id=comp.id, actor_id=admin.id, event_type=EventType.admin_update,
        message="Изменено админом: " + ", ".join(changes) if changes else "Без изменений",
        payload={k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    comp = await session.get(Computer, computer_id, populate_existing=True)
    active = await session.scalar(select(Booking).where(Booking.computer_id == comp.id, Booking.status == "active"))
    return inventory._row(comp, active)


# ---------- Пулы выдачи ----------

@router.get("/pools", response_model=list[PoolOut])
async def list_pools(_: AdminUser, session: DB) -> list[PoolOut]:
    return [
        PoolOut.model_validate(item["pool"]).model_copy(
            update={"total": item["total"], "available": item["available"], "booked": item["booked"]}
        )
        for item in await pools.pool_stats(session)
    ]


@router.post("/pools", response_model=PoolOut, status_code=201)
async def create_pool(data: PoolSave, _: AdminUser, session: DB) -> Pool:
    if not data.name:
        raise HTTPException(422, "Укажите название пула")
    pool = Pool(name=data.name.strip(), description=data.description,
                is_published=True if data.is_published is None else data.is_published)
    session.add(pool)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Пул с таким названием уже есть") from exc
    return pool


@router.patch("/pools/{pool_id}", response_model=PoolOut)
async def update_pool(pool_id: int, data: PoolSave, _: AdminUser, session: DB) -> Pool:
    pool = await session.get(Pool, pool_id)
    if pool is None:
        raise HTTPException(404, "Пул не найден")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(pool, field, value.strip() if isinstance(value, str) else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Пул с таким названием уже есть") from exc
    return pool


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
    limit: int = 50, offset: int = 0,
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
    dept = Department(name=data.name.strip(), code=data.code, head_name=data.head_name)
    session.add(dept)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Отдел с таким названием уже есть") from exc
    return dept


@router.patch("/departments/{department_id}", response_model=DepartmentOut)
async def update_department(department_id: int, data: DepartmentUpdate, _: AdminUser, session: DB) -> Department:
    dept = await session.get(Department, department_id)
    if dept is None:
        raise HTTPException(404, "Отдел не найден")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(dept, field, value.strip() if isinstance(value, str) else value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "Отдел с таким названием уже есть") from exc
    return dept


# ---------- Синхронизация с Insight ----------

@router.get("/sync", response_model=SyncInfoOut)
async def sync_info(_: AdminUser, session: DB) -> SyncInfoOut:
    runs = (await session.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(20))).all()
    return SyncInfoOut(
        mode=settings.insight_mode,
        jira_url=settings.jira_url,
        interval_sec=settings.insight_sync_interval_sec,
        writeback=settings.insight_writeback,
        runs=[SyncRunOut.model_validate(r) for r in runs],
    )


@router.post("/sync", response_model=SyncRunOut)
async def sync_now(_: AdminUser, session: DB) -> SyncRun:
    run = await run_sync(session)
    if run is None:
        raise HTTPException(409, "Синхронизация уже выполняется, попробуйте через минуту")
    return run
