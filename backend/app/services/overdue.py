"""Сроки аренды: просрочки ПК и виртуалок и продления ПК и ВМ.

Видно в Админке → «Сроки аренды» (+ счётчик просрочек и непринятых продлений в меню). Раз в день worker шлёт
в Mattermost (если задан MATTERMOST_WEBHOOK_URL) сводку просрочек и напоминания о скором конце срока.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, workdays
from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.integrations.notify import notify
from app.models import AppSetting, Booking, BookingExtension, BookingStatus, User, VirtualMachine, VmStatus
from app.schemas.admin import OverdueItem
from app.services import runtime

DIGEST_KEY = "overdue_digest_last"  # дата последней сводки (в app_settings)
REMINDERS_KEY = "term_reminders_last"  # дата последних напоминаний о сроке (в app_settings)
DIGEST_HOUR = 10  # во сколько слать сводку и напоминания по местному времени
REMIND_WORKDAYS = 5  # за сколько рабочих дней до конца срока напоминать (DR-15060)
REMIND_HORIZON_DAYS = 31  # дальше этого конец срока заведомо не попадает в напоминание
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


def record_extension(session: AsyncSession, user: User, *, old: date | None, new: date, comment: str | None,
                     booking_id: int | None = None, vm_id: int | None = None) -> None:
    """Продление ПК (booking_id) или ВМ (vm_id) в журнал; вызывается до изменения заказа, чтобы отказ ничего не менял."""
    if old is not None and new <= old:
        raise Conflict(f"Новый срок должен быть позже текущего ({old:%d.%m.%Y})")
    # продление админа уже им «принято»: в счётчик новых попадают только продления арендаторов и их команд
    session.add(BookingExtension(
        booking_id=booking_id, vm_id=vm_id, user_id=user.id, old_return_at=old, new_return_at=new,
        comment=comment or None,
        acknowledged_at=datetime.now(timezone.utc) if user.is_admin else None,
        acknowledged_by_id=user.id if user.is_admin else None,
    ))


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


async def _unsent_today(session: AsyncSession, key: str) -> date | None:
    """Сегодняшний день, если пора слать сообщение `key` (задан вебхук, уже DIGEST_HOUR, сегодня ещё не слали)."""
    if not settings.mattermost_webhook_url:
        return None
    now = clock.now()
    if now.hour < DIGEST_HOUR:
        return None
    row = await session.get(AppSetting, key)
    if row is not None and row.value == now.date().isoformat():
        return None
    return now.date()


async def _mark_sent(session: AsyncSession, key: str, day: date) -> None:
    await runtime.put_setting(session, key, day.isoformat())
    await session.commit()


async def daily_digest(session: AsyncSession) -> None:
    today = await _unsent_today(session, DIGEST_KEY)
    if today is None:
        return
    bookings, vms = await list_overdue(session)
    if bookings or vms:
        lines = [f"⏰ **Просрочки HMS Rent на {today:%d.%m.%Y}**: ПК — {len(bookings)}, виртуалок — {len(vms)}"]
        for b in bookings[:30]:
            lines.append(f"- ПК **{b.computer.name}** (заказ №{b.order_number}) — {b.department.name}, "
                         f"{b.requester_name}, срок {b.expected_return_at:%d.%m}, +{days_overdue(b.expected_return_at)} дн.")
        for vm in vms[:30]:
            lines.append(f"- ВМ **{vm.name}** (заказ №{vm.order_number}) — {vm.department.name}, "
                         f"{vm.requester_name}, срок {vm.expected_return_at:%d.%m}, +{days_overdue(vm.expected_return_at)} дн.")
        await notify("\n".join(lines))
    await _mark_sent(session, DIGEST_KEY, today)


def _reminder_line(kind: str, name: str, order: Booking | VirtualMachine) -> str:
    return (f"- {kind} **{name}** (заказ №{order.order_number}) — {order.department.name}, "
            f"{order.requester_name} ({order.requester_nick}), срок {order.expected_return_at:%d.%m}")


async def daily_reminders(session: AsyncSession) -> None:
    """Раз в рабочий день: в канал Mattermost — чьи аренды кончаются через 5 рабочих дней и у кого сегодня последний
    рабочий день срока (DR-15060, «Окончание срока»). В выходные ничего не шлётся. Позже — личные сообщения (нужен бот)."""
    today = await _unsent_today(session, REMINDERS_KEY)
    if today is None:
        return
    cal = workdays.load()
    if cal.is_workday(today):
        horizon = today + timedelta(days=REMIND_HORIZON_DAYS)
        bookings = (await session.scalars(
            select(Booking).where(Booking.status == BookingStatus.active,
                                  Booking.expected_return_at.between(today, horizon))
            .order_by(Booking.expected_return_at)
        )).unique().all()
        vms = (await session.scalars(
            select(VirtualMachine).where(VirtualMachine.status.in_((VmStatus.ready, VmStatus.failed)),
                                         VirtualMachine.expected_return_at.between(today, horizon))
            .order_by(VirtualMachine.expected_return_at)
        )).unique().all()
        orders = [("ПК", b.computer.name, b) for b in bookings] + [("ВМ", v.name, v) for v in vms]
        soon = [_reminder_line(*o) for o in orders if cal.workdays_before(o[2].expected_return_at, REMIND_WORKDAYS) == today]
        last = [_reminder_line(*o) for o in orders if cal.last_workday(o[2].expected_return_at) == today]
        if soon or last:
            lines = [f"⏳ **Сроки аренды HMS Rent на {today:%d.%m.%Y}**"]
            if soon:
                lines += [f"Через {REMIND_WORKDAYS} рабочих дней заканчивается аренда:", *soon]
            if last:
                lines += ["Сегодня последний рабочий день аренды — верните или продлите:", *last]
            await notify("\n".join(lines))
    await _mark_sent(session, REMINDERS_KEY, today)
