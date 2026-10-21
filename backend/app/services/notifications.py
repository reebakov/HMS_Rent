"""Уведомления заказчику (колокольчик в шапке): ВМ готова или не создана, статус заявки, решение по сроку, конец срока.

Адресат — автор заказа. Тексты без технических подробностей и секретов: детали заказчик видит в «Моей аренде».
Уведомление добавляется в сессию вызывающего и фиксируется вместе с изменением заказа, поэтому одно без другого
не бывает.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.models import Booking, Notification, NotificationKind, ServiceRequest, TermRequest, User, VirtualMachine

LIST_LIMIT = 30  # сколько последних уведомлений отдаёт список
KEEP_DAYS = 90  # старше — удаляются раз в день вместе с напоминаниями о сроке


def add(session: AsyncSession, user_id: int, kind: NotificationKind, title: str, body: str = "") -> None:
    session.add(Notification(user_id=user_id, kind=kind.value, title=title, body=body))


async def list_for(session: AsyncSession, user: User) -> tuple[list[Notification], int]:
    """Последние уведомления (свежие сверху) и общее число непрочитанных."""
    rows = await session.scalars(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(LIST_LIMIT)
    )
    unread = await session.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return list(rows.all()), unread or 0


async def mark_read(session: AsyncSession, user: User, notification_id: int) -> None:
    """Повторный вызов ничего не меняет; чужое уведомление не отличается от несуществующего."""
    row = await session.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id)
    )
    if row is None:
        raise NotFound("Уведомление не найдено")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        await session.commit()


async def mark_all_read(session: AsyncSession, user: User) -> None:
    await session.execute(
        update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def prune(session: AsyncSession) -> None:
    border = datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)
    await session.execute(delete(Notification).where(Notification.created_at < border))
    await session.commit()


def _until(order: Booking | VirtualMachine) -> str:
    return f"{order.expected_return_at:%d.%m.%Y}" if order.expected_return_at else "без срока"


def pc_ready(session: AsyncSession, booking: Booking, *, changed: bool) -> None:
    """Исполнитель внёс данные для подключения к ПК; `changed` — исправил уже внесённые."""
    name = booking.computer.name
    add(session, booking.user_id, NotificationKind.pc_ready,
        f"Данные подключения к ПК {name} изменены" if changed else f"ПК {name} готов",
        f"Заказ №{booking.order_number}, аренда до {_until(booking)}. Адрес и логин — в «Моей аренде», пароль сообщит "
        "исполнитель; смените его при первом входе.")


def vm_ready(session: AsyncSession, vm: VirtualMachine) -> None:
    add(session, vm.user_id, NotificationKind.vm_ready, f"ВМ {vm.name} готова",
        f"Заказ №{vm.order_number}, аренда до {_until(vm)}. Адрес и логин — в «Моей аренде», пароль сообщит исполнитель.")


def vm_failed(session: AsyncSession, vm: VirtualMachine) -> None:
    add(session, vm.user_id, NotificationKind.vm_failed, f"ВМ {vm.name} не создана",
        f"Заказ №{vm.order_number}. Исполнители уведомлены, причина — в «Моей аренде». Заказ можно удалить и оформить заново.")


def request_status(session: AsyncSession, req: ServiceRequest, old: str | None) -> None:
    """Статус заявки в Service Desk сменился; первое получение статуса (old пуст) — не событие."""
    if old is None or old == req.status:
        return
    add(session, req.user_id, NotificationKind.request_status, f"Заявка {req.issue_key}: {req.status}", req.summary)


def term_decision(session: AsyncSession, req: TermRequest, new: date | None) -> None:
    """Решение админа по сроку дольше лимита: `new` — согласованный срок, None — отказ."""
    order = req.vm or req.booking
    kind = "ВМ" if req.vm is not None else "ПК"
    if new is None:
        add(session, req.user_id, NotificationKind.term_decision, f"Срок {kind} {req.name} не согласован",
            f"Заказ №{order.order_number} остаётся со сроком до {_until(order)}.")
    else:
        add(session, req.user_id, NotificationKind.term_decision, f"Срок {kind} {req.name} согласован до {new:%d.%m.%Y}",
            f"Заказ №{order.order_number}.")


def term_ending(session: AsyncSession, kind: str, name: str, order: Booking | VirtualMachine, *, last_day: bool, days: int) -> None:
    title = f"Сегодня последний день аренды {kind} {name}" if last_day else f"Через {days} рабочих дней заканчивается аренда {kind} {name}"
    add(session, order.user_id, NotificationKind.term_ending, title,
        f"Заказ №{order.order_number}, срок до {_until(order)}. Продлите аренду или верните ресурс в «Моей аренде»; "
        "без согласования — до 3 месяцев.")


def term_overdue(session: AsyncSession, kind: str, name: str, order: Booking | VirtualMachine) -> None:
    add(session, order.user_id, NotificationKind.term_overdue, f"Срок аренды {kind} {name} закончился",
        f"Заказ №{order.order_number}, срок был до {_until(order)}. Верните ресурс или продлите аренду в «Моей аренде».")
