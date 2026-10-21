"""Заявки на срок аренды дольше лимита: список для админа, согласование и отказ.

Видно в Админке → «Сроки аренды» (+ счётчик в меню). Согласование ставит срок так же, как продление админом.
"""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.errors import Conflict, NotFound
from app.models import BookingStatus, TermRequest, TermRequestStatus, User, VmStatus
from app.services import bookings, notifications, vms

APPROVED_COMMENT = "Заявка на срок согласована администратором"


def _is_open(req: TermRequest) -> bool:
    """Заказ ещё жив: ПК не возвращён, ВМ не удаляется и не удалена."""
    if req.vm is not None:
        return req.vm.status not in (VmStatus.deleting, VmStatus.deleted)
    return req.booking.status == BookingStatus.active


async def list_pending(session: AsyncSession) -> list[TermRequest]:
    """Ждущие решения заявки, старые сверху; по уже закрытым заказам заявки не показываются."""
    rows = await session.scalars(
        select(TermRequest).where(TermRequest.status == TermRequestStatus.pending).order_by(TermRequest.created_at)
    )
    return [r for r in rows.unique().all() if _is_open(r)]


async def _lock_pending(session: AsyncSession, request_id: int) -> TermRequest:
    req = await session.scalar(
        select(TermRequest).where(TermRequest.id == request_id).with_for_update(of=TermRequest)
    )
    if req is None:
        raise NotFound("Заявка не найдена")
    if req.status != TermRequestStatus.pending:
        raise Conflict("Заявка уже обработана")
    return req


def _decide(req: TermRequest, admin: User, status: TermRequestStatus) -> None:
    req.status = status.value
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by_id = admin.id


async def approve(session: AsyncSession, admin: User, request_id: int, until: date | None) -> TermRequest:
    """Срок заказа становится `until` (по умолчанию — запрошенный). Если нельзя (заказ закрыт, срок не позже текущего), ничего не меняется."""
    req = await _lock_pending(session, request_id)
    new = until or req.requested_return_at
    if new < clock.today():
        raise Conflict("Срок уже в прошлом — укажите другую дату")
    if req.vm_id is not None:
        await vms.apply_term(session, admin, req.vm_id, new, APPROVED_COMMENT)
    else:
        await bookings.apply_term(session, admin, req.booking_id, new, APPROVED_COMMENT)
    _decide(req, admin, TermRequestStatus.approved)
    notifications.term_decision(session, req, new)
    await session.commit()
    return req


async def reject(session: AsyncSession, admin: User, request_id: int) -> TermRequest:
    """Отказ: заказ остаётся с тем сроком, который уже стоит."""
    req = await _lock_pending(session, request_id)
    _decide(req, admin, TermRequestStatus.rejected)
    notifications.term_decision(session, req, None)
    await session.commit()
    return req
