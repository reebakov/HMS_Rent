"""Предельный срок аренды: арендатор получает сразу не дальше 3 месяцев, на больший срок подаётся заявка админу.

Лимит считается от сегодня при заказе и от текущего срока возврата при продлении; администратора он не ограничивает —
он и согласует заявки (services/term_requests.py).
"""
import calendar
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import Conflict
from app.models import TermRequest, User

MAX_TERM_MONTHS = 3


def add_months(day: date, months: int) -> date:
    """Тот же день через `months` месяцев; если такого дня нет (31 → февраль), конец месяца."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def plan(user: User, requested: date, *, base: date | None = None, pending: date | None = None) -> tuple[date, bool]:
    """(срок, который ставится сразу, нужна ли заявка на `requested`).

    base — текущий срок заказа, от которого считать лимит (не раньше сегодня: у просроченного заказа лимит не должен
    оказаться в прошлом), pending — срок уже поданной заявки на этот заказ: вторая заявка, пока первая ждёт решения,
    не принимается.
    """
    if user.is_admin:
        return requested, False
    granted = min(requested, add_months(max(base or clock.today(), clock.today()), MAX_TERM_MONTHS))
    longer = granted < requested
    if longer and pending is not None:
        raise Conflict(f"Заявка на срок до {pending:%d.%m.%Y} уже ждёт решения администратора")
    return granted, longer


def open_request(session: AsyncSession, user: User, *, requested: date, comment: str | None,
                 booking_id: int | None = None, vm_id: int | None = None) -> None:
    session.add(TermRequest(booking_id=booking_id, vm_id=vm_id, user_id=user.id, requested_return_at=requested,
                            comment=comment or None))
