"""Просрочки: ПК и виртуалки, которые должны были вернуть, но не вернули.

Видно в Админке → «Просрочки» (+ счётчик в меню). Раз в день worker шлёт сводку в Mattermost,
если задан MATTERMOST_WEBHOOK_URL.
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.notify import notify
from app.models import AppSetting, Booking, BookingStatus, VirtualMachine

DIGEST_KEY = "overdue_digest_last"  # дата последней сводки (в app_settings)
DIGEST_HOUR = 10  # во сколько слать сводку по местному времени


def _today() -> date:
    return datetime.now(ZoneInfo(settings.display_timezone)).date()


async def list_overdue(session: AsyncSession) -> tuple[list[Booking], list[VirtualMachine]]:
    today = _today()
    bookings = (await session.scalars(
        select(Booking).where(Booking.status == BookingStatus.active, Booking.expected_return_at < today)
        .order_by(Booking.expected_return_at)
    )).unique().all()
    vms = (await session.scalars(
        select(VirtualMachine).where(VirtualMachine.status.in_(("ready", "failed")),
                                     VirtualMachine.expected_return_at < today)
        .order_by(VirtualMachine.expected_return_at)
    )).unique().all()
    return list(bookings), list(vms)


def days_overdue(due: date | None) -> int:
    return (_today() - due).days if due else 0


async def daily_digest(session: AsyncSession) -> None:
    if not settings.mattermost_webhook_url:
        return
    now = datetime.now(ZoneInfo(settings.display_timezone))
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
