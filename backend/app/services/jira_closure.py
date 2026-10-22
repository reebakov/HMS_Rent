"""Закрытие заказов в Jira: портал реагирует на задачи, которые исполнитель закрыл не в портале (DR-15072).

Обратная сторона закрытия из портала (`service_requests._close_if_settled`). Работает в круге worker'а по закрытым задачам
«подготовить ПК» и «Возврат ПК», которые портал ещё не разобрал (`handled_at`). Рабочие правила:
* подготовка закрыта с резолюцией Rejected — заказ отклоняется («Закрыто в Jira», комментарий — последний комментарий
  исполнителя);
* подготовка закрыта иначе, а данных подключения нет — заказ остаётся ждать данных, заказчику уходит уведомление;
* возврат закрыт (не Rejected) — диск считается очищенным, ПК свободен.
Действие выполняется от закрывшего задачу, если он есть в портале, иначе без автора. Повторное открытие задачи в Jira
уже выполненное не откатывает.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError
from app.integrations import servicedesk as sd
from app.models import Booking, BookingStatus, ServiceRequest, ServiceRequestKind, User
from app.services import cleaning, executor, notifications
from app.services.service_requests import last_staff_comment

log = logging.getLogger(__name__)

BATCH = 20
JIRA_REASON = "Закрыто в Jira"
NO_COMMENT = "Задача закрыта в Jira без комментария"


async def _closer(session: AsyncSession, closed_by: tuple[str, str] | None) -> User | None:
    """Пользователь портала по логину или почте автора закрытия в Jira."""
    if not closed_by:
        return None
    name, email = (part.strip().lower() for part in closed_by)
    keys = [k for k in (name, email) if k]
    if not keys:
        return None
    return await session.scalar(select(User).where(or_(func.lower(User.username).in_(keys), func.lower(User.email).in_(keys)))
                                .limit(1))


async def _apply(session: AsyncSession, req: ServiceRequest) -> None:
    booking = await session.get(Booking, req.booking_id, populate_existing=True)
    details = await sd.get_details(req.issue_key)
    rejected = details.resolution == sd.RESOLUTION_REJECTED
    if req.kind == ServiceRequestKind.prepare.value:
        if booking.status == BookingStatus.active and booking.prepared_at is None:
            comment = await last_staff_comment(req.issue_key)
            if rejected:
                await executor.reject(session, await _closer(session, details.closed_by), booking.id, JIRA_REASON,
                                      comment or NO_COMMENT)
            else:
                notifications.work_done_without_data(session, booking, comment)
    elif not rejected and booking.status == BookingStatus.returned:
        if booking.id in {b.id for b in await cleaning.list_waiting(session)}:
            await executor.confirm_cleaned(session, await _closer(session, details.closed_by), booking.id)


async def apply_closures(session: AsyncSession) -> None:
    """Worker: разобрать задачи, закрытые в Jira. Сбой Jira оставляет задачу на следующий круг, гонка с порталом — нет."""
    if not settings.service_desk_configured:
        return
    rows = (await session.scalars(
        select(ServiceRequest).where(
            ServiceRequest.status_category == "done", ServiceRequest.handled_at.is_(None),
            ServiceRequest.kind.in_([ServiceRequestKind.prepare.value, ServiceRequestKind.return_.value]),
            ServiceRequest.booking_id.is_not(None), ServiceRequest.issue_key.is_not(None),
        ).order_by(ServiceRequest.id).limit(BATCH)
    )).unique().all()
    for req in rows:
        try:
            await _apply(session, req)
        except sd.ServiceDeskError as exc:  # до этого момента ничего не менялось: повтор в следующий круг
            log.warning("Закрытие %s в Jira не разобрано, повтор в следующий круг: %s", req.issue_key, exc)
            continue
        except DomainError as exc:  # заказ или ПК уже изменили в портале: разбирать нечего
            log.info("Закрытие %s в Jira: %s", req.issue_key, exc.message)
        req.handled_at = datetime.now(timezone.utc)
        await session.commit()
