"""Просрочки: ПК и виртуалки, которые должны были вернуть, но не вернули.

Видно в Админке → «Просрочки» (+ счётчик в меню). Раз в день worker шлёт сводку в Mattermost,
если задан MATTERMOST_WEBHOOK_URL.
"""
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.integrations.notify import notify
from app.models import AppSetting, Booking, BookingStatus, VirtualMachine, VmStatus
from app.schemas.admin import OverdueItem

DIGEST_KEY = "overdue_digest_last"  # дата последней сводки (в app_settings)
DIGEST_HOUR = 10  # во сколько слать сводку по местному времени


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
    if row is None:
        session.add(AppSetting(key=DIGEST_KEY, value=now.date().isoformat()))
    else:
        row.value = now.date().isoformat()
    await session.commit()
