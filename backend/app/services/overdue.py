"""Сроки аренды: просрочки ПК и виртуалок и продления броней.

Видно в Админке → «Сроки аренды» (+ счётчик просрочек и непринятых продлений в меню). Раз в день worker шлёт
сводку просрочек в Mattermost, если задан MATTERMOST_WEBHOOK_URL.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.core.errors import NotFound
from app.integrations.notify import notify
from app.models import AppSetting, Booking, BookingExtension, BookingStatus, User, VirtualMachine, VmStatus
from app.schemas.admin import OverdueItem
from app.services import runtime

DIGEST_KEY = "overdue_digest_last"  # дата последней сводки (в app_settings)
DIGEST_HOUR = 10  # во сколько слать сводку по местному времени
RECENT_EXTENSIONS_DAYS = 14  # сколько дней принятые продления остаются в списке


async def list_overdue(session: AsyncSession) -> tuple[list[Booking], list[VirtualMachine]]:
    today = clock.today()
    bookings = (await session.scalars(
        select(Booking).where(Booking.status == BookingStatus.active, Booking.expected_return_at < today)
        .order_by(Booking.expected_return_at)
    )).unique().all()
    vms = (await session.scalars(
        select(VirtualMachine).where(VirtualMachine.status.in_((VmStatus.ready, VmStatus.failed)),
                                     VirtualMachine.expected_return_at < today)
        .order_by(VirtualMachine.expected_return_at)
    )).unique().all()
    return list(bookings), list(vms)


async def list_items(session: AsyncSession) -> list[OverdueItem]:
    """Просрочки ПК и ВМ одним списком, самые долгие сверху."""
    bookings, vms = await list_overdue(session)
    items = [
        OverdueItem(kind="pc", id=b.id, order_number=b.order_number, name=b.computer.name, department=b.department.name,
                    requester_name=b.requester_name, requester_nick=b.requester_nick, email=b.user.email,
                    taken_at=b.booked_at, due=b.expected_return_at, days=days_overdue(b.expected_return_at))
        for b in bookings
    ] + [
        OverdueItem(kind="vm", id=v.id, order_number=v.order_number, name=v.name, department=v.department.name,
                    requester_name=v.requester_name, requester_nick=v.requester_nick, email=v.user.email,
                    taken_at=v.ready_at or v.created_at, due=v.expected_return_at,
                    days=days_overdue(v.expected_return_at))
        for v in vms
    ]
    return sorted(items, key=lambda i: -i.days)


async def list_extensions(session: AsyncSession) -> list[BookingExtension]:
    """Непринятые продления и принятые за последние дни: сначала непринятые, внутри — свежие сверху."""
    since = datetime.now(timezone.utc) - timedelta(days=RECENT_EXTENSIONS_DAYS)
    rows = await session.scalars(
        select(BookingExtension)
        .where(BookingExtension.acknowledged_at.is_(None) | (BookingExtension.created_at >= since))
        .order_by(BookingExtension.acknowledged_at.is_not(None), BookingExtension.created_at.desc())
    )
    return list(rows.unique().all())


async def acknowledge_extension(session: AsyncSession, admin: User, extension_id: int) -> BookingExtension:
    """«Принято»: продление больше не считается новым. Повторный вызов ничего не меняет."""
    ext = await session.get(BookingExtension, extension_id)
    if ext is None:
        raise NotFound("Продление не найдено")
    if ext.acknowledged_at is None:
        ext.acknowledged_at = datetime.now(timezone.utc)
        ext.acknowledged_by_id = admin.id
        await session.commit()
        await session.refresh(ext, ["acknowledged_by"])
    return ext


def days_overdue(due: date | None) -> int:
    return (clock.today() - due).days if due else 0


async def daily_digest(session: AsyncSession) -> None:
    if not settings.mattermost_webhook_url:
        return
    now = clock.now()
    if now.hour < DIGEST_HOUR:
        return
    row = await session.get(AppSetting, DIGEST_KEY)
    if row is not None and row.value == now.date().isoformat():
        return
    bookings, vms = await list_overdue(session)
    if bookings or vms:
        lines = [f"⏰ **Просрочки HMS Rent на {now:%d.%m.%Y}**: ПК — {len(bookings)}, виртуалок — {len(vms)}"]
        for b in bookings[:30]:
            lines.append(f"- ПК **{b.computer.name}** (заказ №{b.order_number}) — {b.department.name}, "
                         f"{b.requester_name}, срок {b.expected_return_at:%d.%m}, +{days_overdue(b.expected_return_at)} дн.")
        for vm in vms[:30]:
            lines.append(f"- ВМ **{vm.name}** (заказ №{vm.order_number}) — {vm.department.name}, "
                         f"{vm.requester_name}, срок {vm.expected_return_at:%d.%m}, +{days_overdue(vm.expected_return_at)} дн.")
        await notify("\n".join(lines))
    await runtime.put_setting(session, DIGEST_KEY, now.date().isoformat())
    await session.commit()
