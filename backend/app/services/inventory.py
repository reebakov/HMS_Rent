"""Запросы для админ-панели: сводка, инвентаризация, отделы, журнал, экспорт."""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.db.search import ilike_any
from app.integrations.insight.factory import get_mapping
from app.models import AssetEvent, Booking, BookingStatus, Computer, ComputerStatus, Department, SyncRun, Tier
from app.schemas.admin import (
    DepartmentUsage, InventoryBooking, InventoryRow, StatsOut, SyncRunOut, TierStat,
)
from app.services import runtime

TIER_LABELS = {"weak": "Слабый", "medium": "Средний", "powerful": "Мощный", "vm": "Виртуальная"}
STATUS_LABELS = {
    "available": "Свободен", "booked": "Забронирован", "in_use": "Занят (Insight)",
    "maintenance": "Резерв", "retired": "Списан", "unknown": "Неизвестно",
}


def computer_issues(comp: Computer, booking: Booking | None) -> list[str]:
    """Расхождения между порталом и Insight — то, на что админу стоит посмотреть."""
    mapping = get_mapping()
    insight = mapping.status_map.get((comp.insight_status or "").lower(), mapping.default_status)
    issues: list[str] = []
    if booking and comp.is_archived:
        issues.append("ПК пропал из Insight, но закреплён за отделом")
    if booking and insight in (ComputerStatus.maintenance, ComputerStatus.retired):
        issues.append(f"В Insight статус «{comp.insight_status}», но ПК закреплён за отделом")
    if booking and runtime.current().insight_writeback and not comp.writeback_pending and insight == ComputerStatus.available:
        issues.append("В Insight ПК числится свободным")
    if booking and booking.expected_return_at and booking.expected_return_at < clock.today():
        issues.append(f"Просрочен возврат (до {booking.expected_return_at:%d.%m.%Y})")
    if comp.writeback_error:
        issues.append(f"Ошибка записи в Insight: {comp.writeback_error[:150]}")
    return issues


async def _active_bookings(session: AsyncSession, computer_ids: list[int] | None = None) -> dict[int, Booking]:
    stmt = select(Booking).where(Booking.status == BookingStatus.active)
    if computer_ids is not None:
        stmt = stmt.where(Booking.computer_id.in_(computer_ids))
    rows = await session.scalars(stmt)
    return {b.computer_id: b for b in rows.unique().all()}


def _row(comp: Computer, booking: Booking | None) -> InventoryRow:
    row = InventoryRow.model_validate(comp)
    row.booking = InventoryBooking.model_validate(booking) if booking else None
    row.issues = computer_issues(comp, booking)
    return row


# Проблемы бывают только у забронированных ПК или с ошибкой записи в Insight — проверяем только их
_MAY_HAVE_ISSUES = or_(Computer.status == ComputerStatus.booked, Computer.writeback_error.is_not(None))


async def list_inventory(
    session: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    tier: str | None = None,
    department_id: int | None = None,
    pool_id: str | None = None,  # id пула или "none" — ПК без пула
    issues_only: bool = False,
    include_archived: bool = False,
    limit: int | None = 100,
    offset: int = 0,
) -> tuple[list[InventoryRow], int]:
    stmt = select(Computer)
    if not include_archived:
        stmt = stmt.where(Computer.is_archived.is_(False))
    if status == "unavailable":
        stmt = stmt.where(Computer.status.in_([
            ComputerStatus.maintenance.value, 
            ComputerStatus.in_use.value, 
            ComputerStatus.retired.value, 
            ComputerStatus.unknown.value
        ]))
    elif status:
        stmt = stmt.where(Computer.status == status)
    if tier:
        stmt = stmt.where(Computer.tier == tier)
    if department_id:
        stmt = stmt.where(Computer.department_id == department_id)
    if pool_id == "none":
        stmt = stmt.where(Computer.pool_id.is_(None))
    elif pool_id:
        stmt = stmt.where(Computer.pool_id == int(pool_id))
    if q:
        stmt = stmt.where(ilike_any(
            q, Computer.name, Computer.hostname, Computer.insight_key, Computer.serial_number, Computer.cpu,
            Computer.gpu, Computer.ip_address,
        ))
    # A9 < A10 < A150: сначала по длине имени, потом по алфавиту
    ordered = stmt.order_by(func.length(Computer.name), Computer.name)

    if issues_only:
        computers = (await session.scalars(ordered.where(_MAY_HAVE_ISSUES))).unique().all()
        bookings = await _active_bookings(session, [c.id for c in computers])
        rows = [r for r in (_row(c, bookings.get(c.id)) for c in computers) if r.issues]
        return rows[offset: offset + limit if limit is not None else None], len(rows)

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    if limit is not None:
        ordered = ordered.limit(limit).offset(offset)
    computers = (await session.scalars(ordered)).unique().all()
    bookings = await _active_bookings(session, [c.id for c in computers])
    return [_row(c, bookings.get(c.id)) for c in computers], total or 0


async def get_stats(session: AsyncSession) -> StatsOut:
    alive = Computer.is_archived.is_(False)
    by_status = dict((await session.execute(
        select(Computer.status, func.count()).where(alive).group_by(Computer.status)
    )).all())
    tier_rows = (await session.execute(
        select(
            Computer.tier,
            func.count(),
            func.count().filter(Computer.status == ComputerStatus.available),
            func.count().filter(Computer.status == ComputerStatus.booked),
        ).where(alive).group_by(Computer.tier)
    )).all()
    tiers = {t: TierStat(tier=t, total=n, available=a, booked=b) for t, n, a, b in tier_rows}
    by_tier = [tiers.get(t.value, TierStat(tier=t.value, total=0, available=0, booked=0)) for t in Tier]

    active = (Booking.status == BookingStatus.active)
    active_count, departments_using, overdue = (await session.execute(
        select(
            func.count(),
            func.count(func.distinct(Booking.department_id)),
            func.count().filter(Booking.expected_return_at < clock.today()),
        ).where(active)
    )).one()
    issue_rows, _ = await list_inventory(session, issues_only=True, limit=None)
    in_pools = await session.scalar(select(func.count()).where(alive, Computer.pool_id.is_not(None)))
    last_sync = await session.scalar(select(SyncRun).order_by(SyncRun.id.desc()).limit(1))
    return StatsOut(
        total=sum(by_status.values()),
        by_status=by_status,
        by_tier=by_tier,
        in_pools=in_pools or 0,
        active_bookings=active_count,
        departments_using=departments_using,
        overdue=overdue,
        issues=len(issue_rows),
        last_sync=SyncRunOut.model_validate(last_sync) if last_sync else None,
    )


async def department_usage(session: AsyncSession) -> list[DepartmentUsage]:
    departments = (await session.scalars(select(Department).order_by(Department.name))).all()
    active_by_tier = await session.execute(
        select(Booking.department_id, Computer.tier, func.count())
        .join(Computer, Computer.id == Booking.computer_id)
        .where(Booking.status == BookingStatus.active)
        .group_by(Booking.department_id, Computer.tier)
    )
    totals = await session.execute(
        select(Booking.department_id, func.count(), func.max(Booking.booked_at)).group_by(Booking.department_id)
    )
    tiers: dict[int, dict[str, int]] = defaultdict(dict)
    for dept_id, tier, count in active_by_tier.all():
        tiers[dept_id][tier] = count
    total_map = {dept_id: (count, last) for dept_id, count, last in totals.all()}

    result = [
        DepartmentUsage(
            department_id=d.id,
            name=d.name,
            code=d.code,
            head_name=d.head_name,
            is_active=d.is_active,
            active=sum(tiers[d.id].values()),
            by_tier=tiers[d.id],
            total_bookings=total_map.get(d.id, (0, None))[0],
            last_booked_at=total_map.get(d.id, (0, None))[1],
        )
        for d in departments
    ]
    return sorted(result, key=lambda u: (-u.active, u.name))


async def list_journal(
    session: AsyncSession,
    *,
    status: str | None = None,
    department_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[Booking]:
    stmt = select(Booking).join(Computer, Computer.id == Booking.computer_id).order_by(Booking.booked_at.desc())
    if status:
        stmt = stmt.where(Booking.status == status)
    if department_id:
        stmt = stmt.where(Booking.department_id == department_id)
    if date_from:
        stmt = stmt.where(Booking.booked_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        stmt = stmt.where(Booking.booked_at <= datetime.combine(date_to, time.max, timezone.utc))
    if q:
        stmt = stmt.where(ilike_any(q, Computer.name, Booking.requester_name, Booking.requester_nick))
    return list((await session.scalars(stmt.limit(limit))).unique().all())


async def list_events(
    session: AsyncSession, 
    *, 
    computer_id: int | None = None,
    event_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0
) -> tuple[list[AssetEvent], int]:
    stmt = select(AssetEvent).join(Computer, Computer.id == AssetEvent.computer_id)
    
    if computer_id:
        stmt = stmt.where(AssetEvent.computer_id == computer_id)
    if event_type:
        stmt = stmt.where(AssetEvent.event_type == event_type)
    if date_from:
        stmt = stmt.where(AssetEvent.created_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        stmt = stmt.where(AssetEvent.created_at <= datetime.combine(date_to, time.max, timezone.utc))
    if q:
        stmt = stmt.where(ilike_any(q, Computer.name, AssetEvent.message))

    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    
    stmt = stmt.order_by(AssetEvent.created_at.desc(), AssetEvent.id.desc()).limit(limit).offset(offset)
    items = list((await session.scalars(stmt)).unique().all())
    return items, total or 0


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value):
    """Строка, которую Excel примет за формулу («=HYPERLINK(...)»), получает префикс «'» — остаётся текстом.

    Имя и ник в брони вводит любой сотрудник, а выгрузку открывает админ.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def inventory_csv(rows: list[InventoryRow]) -> str:
    """CSV для Excel: разделитель «;» и BOM — так русские буквы открываются без танцев."""
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "ПК", "Ключ Insight", "Категория", "Процессор", "ОЗУ, ГБ", "Диск", "Видеокарта", "ОС", "Расположение",
        "Серийный номер", "Статус портала", "Статус Insight", "Пул выдачи", "Команда-получатель", "Номер заказа",
        "Забронировал", "Ник", "С даты", "Срок использования", "Расхождения",
    ])
    for r in rows:
        b = r.booking
        w.writerow(_safe_cell(c) for c in [
            r.name, r.insight_key or "", TIER_LABELS.get(r.tier, r.tier), r.cpu or "", r.ram_gb or "",
            r.storage or "", r.gpu or "", r.os or "", r.location or "", r.serial_number or "",
            STATUS_LABELS.get(r.status, r.status), r.insight_status or "",
            r.pool.name if r.pool else "", r.department.name if r.department else "", r.order_number or "",
            b.requester_name if b else "", b.requester_nick if b else "",
            f"{b.booked_at.astimezone(clock.display_tz()):%d.%m.%Y %H:%M}" if b else "",
            f"{r.usage_until:%d.%m.%Y}" if r.usage_until else "",
            " | ".join(r.issues),
        ])
    return buf.getvalue()
