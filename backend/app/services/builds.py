"""Сборка по запросу: исполнитель выдаёт собранный ПК заказчику или отклоняет заказ, заказчик может его отменить.

Регламент, раздел 3: заказ на сборку приходит задачей Jira; собрав ПК и заведя его в Insight (статус «Используется»),
исполнитель в портале указывает этот ПК, пул и данные подключения — портал создаёт бронь с номером, сроком, ОС и ником
из заказа, как при обычной выдаче. После возврата ПК остаётся в выбранном пуле. Задачу в Jira закрывает портал.
"""
import re
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.integrations.notify import notify
from app.integrations.servicedesk import agent_url
from app.models import (
    Booking,
    BookingStatus,
    Computer,
    ComputerStatus,
    EventType,
    Pool,
    ServiceRequest,
    ServiceRequestKind,
    User,
)
from app.schemas.booking import ExecutorBuildIssue, ExecutorBuildOut, PoolShort
from app.services import notifications, runtime, service_requests, term_limit
from app.services.access import ensure_access
from app.services.events import add_event
from app.services.orders import requester_name

LIST_LIMIT = 200
ISSUABLE = (ComputerStatus.in_use, ComputerStatus.available, ComputerStatus.unknown)  # в Insight ПК уже «Используется»
CONFIGURATION = re.compile(r"^(?:Сборка|Своя конфигурация): (.+)$", re.M)


async def _lock(session: AsyncSession, request_id: int, *, for_issue: bool = True) -> ServiceRequest:
    req = await session.scalar(
        select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update(of=ServiceRequest)
        .execution_options(populate_existing=True)
    )
    if req is None or req.kind != ServiceRequestKind.build.value:
        raise NotFound("Заказ на сборку не найден")
    if req.portal_done_at is not None:
        raise Conflict("Заказ на сборку уже обработан")
    if for_issue and req.payload is None:
        raise Conflict("Заказ создан до выдачи сборок в портале: ПК выдаётся вне портала, закройте задачу в Jira")
    return req


def _out(req: ServiceRequest) -> ExecutorBuildOut:
    p = req.payload or {}
    match = CONFIGURATION.search(req.description)
    return ExecutorBuildOut(
        id=req.id, order_number=p["order_number"], configuration=match.group(1) if match else req.summary,
        os_label=p.get("os_label"), department=req.department, user=req.user, requester_nick=p["requester_nick"],
        purpose=p.get("purpose"), expected_return_at=date.fromisoformat(p["expected_return_at"]),
        wanted_by=date.fromisoformat(p["wanted_by"]) if p.get("wanted_by") else None, created_at=req.created_at,
        request_key=req.issue_key, request_url=agent_url(req.issue_key) if req.issue_key else None,
        request_status=req.status, request_error=req.error, request_done=req.status_category == "done",
    )


async def list_builds(session: AsyncSession) -> list[ExecutorBuildOut]:
    """Заказы на сборку, ждущие выдачи: сначала с желаемым сроком (раньше срок — выше), затем давние (заявки без данных
    заказа, созданные до миграции, не показываются)."""
    rows = await session.scalars(
        select(ServiceRequest).where(ServiceRequest.kind == ServiceRequestKind.build.value,
                                     ServiceRequest.payload.is_not(None), ServiceRequest.portal_done_at.is_(None))
        .order_by(ServiceRequest.created_at, ServiceRequest.id).limit(LIST_LIMIT)
    )
    # желаемый срок («нужен к») — раньше всех остальных, дальше по времени поступления (регламент, раздел 1)
    return sorted((_out(r) for r in rows.unique()),
                  key=lambda b: (b.wanted_by is None, b.wanted_by or date.max, b.created_at, b.id))


async def list_pools(session: AsyncSession) -> list[PoolShort]:
    return [PoolShort.model_validate(p) for p in (await session.scalars(
        select(Pool).where(Pool.is_published.is_(True)).order_by(Pool.name)))]


async def issue(session: AsyncSession, user: User, request_id: int, data: ExecutorBuildIssue) -> Booking:
    """Выдать собранный ПК: бронь на команду заказчика с данными подключения, ПК в выбранном пуле, заказчику уведомление."""
    req = await _lock(session, request_id)
    p = req.payload
    comp = await session.scalar(
        select(Computer).where(func.lower(Computer.name) == data.computer_name.strip().lower())
        .with_for_update(of=Computer).execution_options(populate_existing=True)
    )
    if comp is None:
        raise NotFound(f"ПК «{data.computer_name.strip()}» нет в портале: проверьте имя и дождитесь синхронизации с Insight")
    if comp.is_archived or comp.is_virtual:
        raise Conflict(f"{comp.name} недоступен для выдачи (архивный или виртуальный)")
    if comp.status not in ISSUABLE:
        hint = " В Insight он ещё «Закрыто»: заполните объект и дождитесь синхронизации." if comp.status == ComputerStatus.retired else ""
        raise Conflict(f"{comp.name} сейчас нельзя выдать: статус «{comp.status}».{hint}")
    if await session.scalar(select(Booking.id).where(Booking.computer_id == comp.id, Booking.status == BookingStatus.active).limit(1)):
        raise Conflict(f"{comp.name} уже выдан по другому заказу")
    pool = await session.get(Pool, data.pool_id)
    if pool is None:
        raise NotFound("Пул не найден")

    customer = await session.get(User, req.user_id)
    until, longer = term_limit.plan(customer, date.fromisoformat(p["expected_return_at"]))
    now = datetime.now(timezone.utc)
    booking = Booking(
        computer_id=comp.id, department_id=req.department_id, user_id=customer.id, order_number=p["order_number"],
        requester_name=requester_name(customer), requester_nick=p["requester_nick"], purpose=p.get("purpose"),
        os_label=p.get("os_label"), expected_return_at=until, connection_host=data.host, connection_ip=str(data.ip),
        connection_method=data.method, prepared_at=now, prepared_by_id=user.id,
    )
    session.add(booking)
    await session.flush()
    if longer:
        term_limit.open_request(session, customer, requested=date.fromisoformat(p["expected_return_at"]), comment=None,
                                booking_id=booking.id)
    add_event(session, computer_id=comp.id, booking_id=booking.id, actor_id=user.id, event_type=EventType.booked,
              from_status=comp.status, to_status=ComputerStatus.booked.value,
              message=f"Заказ №{booking.order_number}: собранный ПК выдан отделу «{req.department.name}», пул «{pool.name}»")
    add_event(session, computer_id=comp.id, booking_id=booking.id, actor_id=user.id, event_type=EventType.prepared,
              message=f"Заказ №{booking.order_number}: ПК подготовлен — {data.host}, {data.ip}, {data.method}")
    comp.status, comp.pool_id, comp.department_id = ComputerStatus.booked.value, pool.id, booking.department_id
    comp.usage_until, comp.order_number = booking.expected_return_at, booking.order_number
    comp.writeback_pending = runtime.current().insight_writeback
    req.booking_id, req.portal_done_at = booking.id, now
    notifications.pc_ready(session, booking, changed=False)
    await session.commit()

    await notify(f"🛠 Собранный ПК **{comp.name}** выдан по заказу №{booking.order_number} ({req.department.name}, пул «{pool.name}»)")
    return booking


async def reject(session: AsyncSession, user: User | None, request_id: int, reason: str, comment: str) -> None:
    """Заказ на сборку отклонён: заказчик получает причину, задачу в Jira портал закроет с резолюцией Rejected.

    `user` пуст, если задачу закрыл в Jira тот, кого нет в портале.
    """
    req = await _lock(session, request_id, for_issue=False)
    req.resolution, req.portal_done_at = "Rejected", datetime.now(timezone.utc)
    notifications.build_rejected(session, req, reason, comment)
    await session.commit()
    await notify(f"🚫 Заказ №{(req.payload or {}).get('order_number', '')} на сборку ПК отклонён исполнителем: {reason}")


async def cancel(session: AsyncSession, user: User, request_id: int) -> None:
    """Заказчик отменяет заказ на сборку, пока задача в Backlog; исполнитель уже взял её — 409."""
    req = await session.get(ServiceRequest, request_id)
    if req is None or req.kind != ServiceRequestKind.build.value:
        raise NotFound("Заказ на сборку не найден")
    ensure_access(user, req.user_id, req.department_id, "Отменить заказ может его автор, участник его команды или администратор")
    if req.portal_done_at is not None or req.status_category == "done":
        raise Conflict("Заказ уже выполнен или отклонён")
    await service_requests.is_untouched(session, request=req)  # Conflict, если исполнитель задачу уже взял
    req = await _lock(session, request_id, for_issue=False)
    req.resolution, req.portal_done_at = "Rejected", datetime.now(timezone.utc)
    await session.commit()
    await notify(f"↩️ Заказчик отменил заказ на сборку ПК (№{(req.payload or {}).get('order_number', '')}, {req.department.name})")
