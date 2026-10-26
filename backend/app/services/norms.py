"""Нормативы исполнителей (регламент, раздел 1): задачу берут за 1 рабочий час (возврат ПК — за рабочий день), срок работы
зависит от вида задачи.

Рабочее время — 10:00–18:00 GMT+7 рабочих дней по производственному календарю. Пока задача «Заморожена», норматив стоит
на паузе. Нарушение портал только сообщает в канал исполнителей Mattermost (один раз на задачу и на вид нарушения).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import workdays
from app.core.config import settings
from app.integrations.notify import notify
from app.integrations.servicedesk import agent_url
from app.models import ServiceRequest, ServiceRequestKind

log = logging.getLogger(__name__)

TAKE_KINDS = (ServiceRequestKind.prepare, ServiceRequestKind.return_, ServiceRequestKind.build, ServiceRequestKind.diagnose)
NOT_TAKEN = ("Backlog", "To Do")  # статусы «никто не взял»
BATCH = 200


def take_limit(req: ServiceRequest) -> tuple[int, str]:
    """За сколько рабочих секунд задачу нужно взять и название срока для сообщения: час, а возврат ПК (очистка диска) —
    рабочий день: сервер вернули, но очистка не срочная, и час был бы слишком жёсткой границей."""
    if req.kind == ServiceRequestKind.return_:
        return workdays.WORK_DAY, "1 рабочий день"
    return workdays.WORK_HOUR, "1 рабочий час"


def norm(req: ServiceRequest) -> tuple[int, str] | None:
    """Норматив на выполнение задачи в рабочих секундах и его название для сообщения; для остальных видов его нет."""
    if req.kind == ServiceRequestKind.prepare and req.vm_id is not None:
        return 2 * workdays.WORK_HOUR, "2 рабочих часа"  # проверка ВМ
    if req.kind in (ServiceRequestKind.prepare, ServiceRequestKind.return_):
        return workdays.WORK_DAY, "1 рабочий день"  # выдача сервера из пула, возврат физического сервера
    if req.kind == ServiceRequestKind.build:
        return 3 * workdays.WORK_DAY, "3 рабочих дня"
    return None


def _hours(seconds: int) -> str:
    return f"{seconds / workdays.WORK_HOUR:.1f}".replace(".0", "")


def _link(req: ServiceRequest) -> str:
    return f"[{req.issue_key}]({agent_url(req.issue_key)}) «{req.summary}»"


async def check(session: AsyncSession) -> None:
    """Worker: сообщить в канал о задачах, не взятых в срок, и о нарушенных нормативах."""
    if not settings.service_desk_configured:
        return
    rows = (await session.scalars(
        select(ServiceRequest).where(
            ServiceRequest.issue_key.is_not(None), func.coalesce(ServiceRequest.status_category, "") != "done",
            ServiceRequest.kind.in_([k.value for k in TAKE_KINDS]),
            ServiceRequest.take_alerted_at.is_(None) | ServiceRequest.norm_alerted_at.is_(None),
        ).order_by(ServiceRequest.id).limit(BATCH)
    )).unique().all()
    if not rows:
        return
    cal, now = workdays.load(), datetime.now(timezone.utc)
    for req in rows:
        elapsed = cal.working_seconds(req.created_at, now)
        take_seconds, take_name = take_limit(req)
        if req.take_alerted_at is None and req.workflow_status in NOT_TAKEN and elapsed > take_seconds:
            req.take_alerted_at = now
            await notify(f"⏰ Задача {_link(req)} не взята за {take_name}")
        limit = norm(req)
        if limit and req.norm_alerted_at is None:
            paused = (req.frozen_work_seconds or 0) + (cal.working_seconds(req.frozen_since, now) if req.frozen_since else 0)
            spent = elapsed - paused
            if spent > limit[0]:
                req.norm_alerted_at = now
                await notify(f"🚨 Нарушен норматив по задаче {_link(req)}: норматив {limit[1]}, "
                             f"прошло {_hours(spent)} рабочих ч (время заморозки не считается)")
    await session.commit()
