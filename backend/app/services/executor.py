"""Раздел «Исполнитель»: очередь выданных ПК и данные для подключения, которые исполнитель вносит после подготовки.

Первый этап интерфейса исполнителя (DR-15075): заявка Service Desk «подготовить ПК» остаётся задачей для исполнителя
и ведёт на страницу заказа, а результат вносится в портале, и заказчик видит его в «Моей аренде».
"""
from datetime import datetime, timezone
from ipaddress import IPv4Address

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.db.session import SessionLocal
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
    VirtualMachine,
    VmStatus,
)
from app.schemas.booking import (
    FAULTY_REASON,
    ExecutorDiagnosticOut,
    ExecutorOrderOut,
    ExecutorProblemOut,
    ExecutorReject,
    ExecutorReplace,
    ExecutorResult,
    ProblemTransitionOut,
    ReplacementOut,
)
from app.schemas.vm import ExecutorVmOut
from app.services import cleaning, notifications, runtime, service_requests
from app.services.bookings import get_booking, status_after_return
from app.services.catalog import natural_key
from app.services.events import add_event
from app.services.pools import pool_visible, visible_pool_ids

LIST_LIMIT = 200


def _insight_ip(raw: str | None) -> str | None:
    """Адрес из Insight как подсказка: только один корректный IPv4, иначе исполнитель введёт сам."""
    try:
        return str(IPv4Address((raw or "").strip()))
    except ValueError:
        return None


async def orders_out(session: AsyncSession, bookings: list[Booking],
                     kind: ServiceRequestKind = ServiceRequestKind.prepare) -> list[ExecutorOrderOut]:
    """Заказы со ссылкой на заявку Service Desk («подготовить ПК», для возвратов — «Возврат ПК»): из портала в Jira."""
    requests = await session.scalars(
        select(ServiceRequest).where(ServiceRequest.kind == kind.value,
                                     ServiceRequest.booking_id.in_([b.id for b in bookings])).order_by(ServiceRequest.id)
    )
    by_booking = {r.booking_id: r for r in requests.unique()}  # при нескольких заявках — последняя
    rows = []
    for booking in bookings:
        row = ExecutorOrderOut.model_validate(booking)
        row.insight_ip = _insight_ip(booking.computer.ip_address)
        if req := by_booking.get(booking.id):
            row.request_key, row.request_status, row.request_error = req.issue_key, req.status, req.error
            row.request_url = agent_url(req.issue_key) if req.issue_key else None
            row.request_done = req.status_category == "done"
        rows.append(row)
    return rows


async def order_out(session: AsyncSession, booking: Booking,
                    kind: ServiceRequestKind = ServiceRequestKind.prepare) -> ExecutorOrderOut:
    return (await orders_out(session, [booking], kind))[0]


CONTEXT_SEPARATOR = "\n\n---\n"  # после него в описании заявки идут данные ПК/ВМ, их исполнитель видит в Jira


async def list_problems(session: AsyncSession) -> list[ExecutorProblemOut]:
    """Проблемы по заказам: сначала открытые, затем закрытые, внутри — свежие выше."""
    requests = (await session.scalars(
        select(ServiceRequest).where(ServiceRequest.kind == ServiceRequestKind.problem.value)
        .order_by(func.coalesce(ServiceRequest.status_category, "") == "done", ServiceRequest.created_at.desc(),
                  ServiceRequest.id.desc())
        .limit(LIST_LIMIT)
    )).unique().all()
    return await _problems_out(session, list(requests))


async def _problems_out(session: AsyncSession, requests: list[ServiceRequest]) -> list[ExecutorProblemOut]:
    bookings = {b.id: b for b in (await session.scalars(
        select(Booking).where(Booking.id.in_([r.booking_id for r in requests if r.booking_id])))).unique()}
    vms = {v.id: v for v in (await session.scalars(
        select(VirtualMachine).where(VirtualMachine.id.in_([r.vm_id for r in requests if r.vm_id])))).unique()}
    computers = {c.id: c for c in (await session.scalars(
        select(Computer).where(Computer.id.in_([r.computer_id for r in requests if r.computer_id and not r.booking_id
                                                  and not r.vm_id])))).unique()}
    rows = []
    for req in requests:
        booking, vm, outside = bookings.get(req.booking_id), vms.get(req.vm_id), computers.get(req.computer_id)
        item = booking or vm
        rows.append(ExecutorProblemOut(
            id=req.id, issue_key=req.issue_key, issue_url=agent_url(req.issue_key) if req.issue_key else None,
            status=req.status, status_category=req.status_category, error=req.error,
            message=req.description.split(CONTEXT_SEPARATOR, 1)[0], created_at=req.created_at, reporter=req.user,
            # ПК вне портала: брони нет, отдел — «Команда-получатель» (или отдел автора, если ПК уже вернули)
            department=item.department if item else (outside.department if outside and outside.department else req.user.department),
            order_number=item.order_number if item else None,
            target_name=booking.computer.name if booking else vm.name if vm else outside.name if outside else "ПК", is_vm=vm is not None,
            booking_id=booking.id if booking else None,
        ))
    return rows


async def _problem(session: AsyncSession, request_id: int) -> ServiceRequest:
    req = await session.get(ServiceRequest, request_id)
    if req is None or req.kind != ServiceRequestKind.problem.value:
        raise NotFound("Проблема не найдена")
    if not req.issue_key:
        raise Conflict("Задача в Jira не создана: переводить нечего")
    return req


async def problem_transitions(session: AsyncSession, request_id: int) -> list[ProblemTransitionOut]:
    """Переходы задачи по проблеме, доступные из её статуса в Jira."""
    req = await _problem(session, request_id)
    return [ProblemTransitionOut(id=str(t["id"]), name=t.get("name") or "", to_status=(t.get("to") or {}).get("name") or "",
                                 closes=service_requests.sd.is_done_transition(t))
            for t in await service_requests.available_transitions(req)]


async def move_problem(session: AsyncSession, request_id: int, transition_id: str,
                       comment: str | None = None) -> ExecutorProblemOut:
    """Исполнитель переводит задачу по проблеме в новый статус прямо из портала; комментарий уходит заказчику публично."""
    req = await _problem(session, request_id)
    await service_requests.move_issue(session, req, transition_id, comment)
    return (await _problems_out(session, [req]))[0]


async def list_orders(session: AsyncSession) -> list[Booking]:
    """Активные брони: сначала ждущие подготовки (давние выше), затем подготовленные."""
    rows = await session.scalars(
        select(Booking).where(Booking.status == BookingStatus.active.value)
        .order_by(Booking.prepared_at.is_not(None), Booking.booked_at, Booking.id).limit(LIST_LIMIT)
    )
    return list(rows.unique().all())


async def save_result(session: AsyncSession, user: User, booking_id: int, data: ExecutorResult) -> Booking:
    """Данные для подключения к подготовленному ПК; повторная отправка тех же данных ничего не меняет."""
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking)
        .execution_options(populate_existing=True)
    )
    if booking is None:
        raise NotFound("Заказ не найден")
    if booking.status != BookingStatus.active:
        raise Conflict("Заказ уже закрыт: ПК вернули")
    values = (data.host, str(data.ip), data.method)
    if booking.prepared_at and (booking.connection_host, booking.connection_ip, booking.connection_method) == values:
        return booking

    changed = booking.prepared_at is not None
    booking.connection_host, booking.connection_ip, booking.connection_method = values
    booking.prepared_at, booking.prepared_by_id = datetime.now(timezone.utc), user.id
    add_event(
        session,
        computer_id=booking.computer_id,
        booking_id=booking.id,
        actor_id=user.id,
        event_type=EventType.prepared,
        message=f"Заказ №{booking.order_number}: {'данные подключения изменены' if changed else 'ПК подготовлен'} — "
                f"{data.host}, {data.ip}, {data.method}",
    )
    notifications.pc_ready(session, booking, changed=changed)
    await session.commit()
    return await get_booking(session, booking.id)


async def reject_order(session: AsyncSession, user: User, booking_id: int, data: ExecutorReject) -> Booking:
    return await reject(session, user, booking_id, data.reason, data.comment)


async def reject(session: AsyncSession, user: User | None, booking_id: int, reason: str, comment: str) -> Booking:
    """Заказ ПК отклонён: бронь закрывается как cancelled, ПК освобождается, заказчик видит причину.

    «Сервер неисправен» дополнительно выводит ПК из пула и ставит ему статус «Обслуживание»; заявку «Диагностика
    комплекта» создаёт маршрут в фоне. Имя исполнителя остаётся только в журнале ПК: заказчику оно не показывается.
    `user` пуст, если заказ закрыт в Jira тем, кого нет в портале.
    """
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking)
        .execution_options(populate_existing=True)
    )
    if booking is None:
        raise NotFound("Заказ не найден")
    if booking.status != BookingStatus.active:
        raise Conflict("Заказ уже закрыт")
    comp = await session.scalar(
        select(Computer).where(Computer.id == booking.computer_id).with_for_update(of=Computer)
    )
    faulty = reason == FAULTY_REASON

    booking.status = BookingStatus.cancelled.value
    booking.returned_at = datetime.now(timezone.utc)
    booking.return_comment = f"{reason}: {comment}"  # returned_by не заполняем: заказчик не должен видеть исполнителя
    new_status = ComputerStatus.maintenance.value if faulty else status_after_return(comp)
    add_event(
        session,
        computer_id=comp.id,
        booking_id=booking.id,
        actor_id=user.id if user else None,
        event_type=EventType.rejected,
        from_status=comp.status,
        to_status=new_status,
        message=f"Заказ №{booking.order_number} отклонён: {reason}. {comment}"
                + (" ПК выведен из пула." if faulty else ""),
    )
    comp.status = new_status
    comp.department_id = None
    comp.usage_until = None
    comp.order_number = None
    if faulty:
        comp.faulty = True
        session.add(service_requests.new_diagnose(booking, comp.pool, user, comment))  # помнит прежний пул ПК
        comp.pool_id = None
    comp.writeback_pending = runtime.current().insight_writeback
    notifications.order_rejected(session, booking, reason, comment)
    await session.commit()

    await notify(f"🚫 Заказ №{booking.order_number} на **{comp.name}** отклонён исполнителем: {reason}")
    return await get_booking(session, booking.id)


async def list_replacements(session: AsyncSession, booking_id: int) -> list[ReplacementOut]:
    """Свободные ПК той же категории из пулов, видимых команде заказа: на них можно заменить неисправный."""
    booking = await get_booking(session, booking_id)
    old = await session.get(Computer, booking.computer_id)
    rows = (await session.scalars(
        select(Computer).where(
            Computer.status == ComputerStatus.available, Computer.is_archived.is_(False), Computer.tier == old.tier,
            Computer.id != old.id, Computer.pool_id.in_(visible_pool_ids(booking.user)),
        )
    )).unique().all()
    return [ReplacementOut(id=c.id, name=c.name, tier=c.tier, cpu=c.cpu, ram_gb=c.ram_gb, storage=c.storage, gpu=c.gpu,
                           pool_name=c.pool.name if c.pool else None)
            for c in sorted(rows, key=lambda c: natural_key(c.name))]


async def replace_computer(session: AsyncSession, user: User, booking_id: int, data: ExecutorReplace) -> Booking:
    """Неисправный ПК в ещё не подготовленном заказе заменяется другим свободным ПК той же категории.

    Заказ остаётся тем же (номер, срок, ОС, отдел): новый ПК получает бронь, неисправный уходит в диагностику как при
    «Сервер неисправен» (из пула выводится, создаётся заявка). Заказчик получает уведомление о замене.
    """
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking)
        .execution_options(populate_existing=True)
    )
    if booking is None:
        raise NotFound("Заказ не найден")
    if booking.status != BookingStatus.active:
        raise Conflict("Заказ уже закрыт")
    if booking.prepared_at is not None:
        raise Conflict("ПК уже подготовлен и выдан заказчику: замена недоступна, отклоните заказ или ведите работу в заявке")
    if data.computer_id == booking.computer_id:
        raise Conflict("Это тот же ПК")
    first, second = sorted((booking.computer_id, data.computer_id))
    locked = {c.id: c for c in (await session.scalars(
        select(Computer).where(Computer.id.in_((first, second))).order_by(Computer.id).with_for_update(of=Computer)
        .execution_options(populate_existing=True)
    )).unique()}
    old, new = locked[booking.computer_id], locked.get(data.computer_id)
    if new is None:
        raise NotFound("ПК для замены не найден")
    if new.status != ComputerStatus.available or new.is_archived:
        raise Conflict(f"{new.name} сейчас недоступен: выберите другой ПК")
    if new.tier != old.tier or not pool_visible(new.pool, booking.user):
        raise Conflict(f"{new.name} не подходит: нужен свободный ПК той же категории из пула команды заказа")

    writeback = runtime.current().insight_writeback
    session.add(service_requests.new_diagnose(booking, old.pool, user, f"{data.comment} (заменён на {new.name})"))
    add_event(session, computer_id=old.id, booking_id=booking.id, actor_id=user.id, event_type=EventType.replaced,
              from_status=old.status, to_status=ComputerStatus.maintenance.value,
              message=f"Заказ №{booking.order_number} переведён на {new.name}: {data.comment}. ПК выведен из пула.")
    add_event(session, computer_id=new.id, booking_id=booking.id, actor_id=user.id, event_type=EventType.replaced,
              from_status=new.status, to_status=ComputerStatus.booked.value,
              message=f"Заказ №{booking.order_number}: ПК заменил {old.name}")
    old.status, old.pool_id, old.department_id, old.usage_until, old.order_number = (
        ComputerStatus.maintenance.value, None, None, None, None)
    old.faulty = True
    new.status, new.department_id = ComputerStatus.booked.value, booking.department_id
    new.usage_until, new.order_number = booking.expected_return_at, booking.order_number
    old.writeback_pending = new.writeback_pending = writeback
    booking.computer_id = new.id
    notifications.pc_replaced(session, booking, old.name, new.name)
    await session.commit()

    await notify(f"🔁 В заказе №{booking.order_number} **{old.name}** заменён на **{new.name}**: {data.comment}")
    return await get_booking(session, booking.id)


async def rename_prepare_task(booking_id: int) -> None:
    """После замены ПК тема задачи «подготовить ПК» в Jira получает имя нового ПК (в фоне; сбой Jira — только в лог)."""
    async with SessionLocal() as session:
        await service_requests.rename_prepare(session, booking_id)


async def send_diagnose_request(computer_id: int, user_id: int) -> None:
    """Заявка «Диагностика комплекта» в Service Desk — в фоне, после отметки «Сервер неисправен»."""
    async with SessionLocal() as session:
        actor = await session.get(User, user_id)
        if actor is not None:
            await service_requests.send_diagnose(session, computer_id, actor)


def _comment_of(req: ServiceRequest) -> str:
    """Комментарий исполнителя из описания заявки: строка после «Комментарий исполнителя:»."""
    for line in req.description.splitlines():
        if line.startswith("Комментарий исполнителя:"):
            return line.split(":", 1)[1].strip()
    return ""


async def list_diagnostics(session: AsyncSession) -> list[ExecutorDiagnosticOut]:
    """ПК на диагностике: заявка «Диагностика комплекта» с привязкой к ПК, который ещё не вернули в пул."""
    requests = (await session.scalars(
        select(ServiceRequest).join(Computer, Computer.id == ServiceRequest.computer_id)
        .where(ServiceRequest.kind == ServiceRequestKind.diagnose.value, ServiceRequest.portal_done_at.is_(None),
               Computer.status == ComputerStatus.maintenance)
        .order_by(ServiceRequest.created_at, ServiceRequest.id).limit(LIST_LIMIT)
    )).unique().all()
    return [await _diagnostic_out(session, req) for req in requests]


async def _diagnostic_out(session: AsyncSession, req: ServiceRequest) -> ExecutorDiagnosticOut:
    computer = await session.get(Computer, req.computer_id)
    pool = await session.get(Pool, req.pool_id) if req.pool_id else None
    return ExecutorDiagnosticOut(
        id=req.id, computer=computer, pool_name=pool.name if pool else None, comment=_comment_of(req),
        created_at=req.created_at, issue_key=req.issue_key,
        issue_url=agent_url(req.issue_key) if req.issue_key else None, status=req.status, error=req.error,
        request_done=req.status_category == "done",
    )


async def repair_computer(session: AsyncSession, user: User | None, request_id: int) -> ExecutorDiagnosticOut:
    """Диагностика закончена: ПК возвращается в прежний пул и становится свободным, в Insight пишется «Ожидает».

    `user` пуст, если задачу закрыл в Jira тот, кого нет в портале.
    """
    req = await session.get(ServiceRequest, request_id)
    if req is None or req.kind != ServiceRequestKind.diagnose.value or req.computer_id is None:
        raise NotFound("Диагностика не найдена")
    comp = await session.scalar(
        select(Computer).where(Computer.id == req.computer_id).with_for_update(of=Computer)
        .execution_options(populate_existing=True)
    )
    if comp.status != ComputerStatus.maintenance:
        raise Conflict(f"{comp.name} уже не на диагностике")
    pool = await session.get(Pool, req.pool_id) if req.pool_id else None
    add_event(
        session,
        computer_id=comp.id,
        actor_id=user.id if user else None,
        event_type=EventType.repaired,
        from_status=comp.status,
        to_status=ComputerStatus.available.value,
        message="Диагностика закончена, ПК свободен" + (f" и возвращён в пул «{pool.name}»" if pool else ", прежний пул не известен"),
    )
    comp.status = ComputerStatus.available.value
    comp.faulty = False
    if pool is not None:
        comp.pool_id = pool.id
    comp.writeback_pending = runtime.current().insight_writeback
    req.portal_done_at = datetime.now(timezone.utc)
    await session.commit()
    await notify(f"🛠 **{comp.name}** после диагностики свободен" + (f", возвращён в пул «{pool.name}»" if pool else ""))
    return await _diagnostic_out(session, req)


async def _vm_requests(session: AsyncSession, vms: list[VirtualMachine]) -> dict[int, ServiceRequest]:
    requests = await session.scalars(
        select(ServiceRequest).where(ServiceRequest.kind == ServiceRequestKind.prepare.value,
                                     ServiceRequest.vm_id.in_([v.id for v in vms])).order_by(ServiceRequest.id)
    )
    return {r.vm_id: r for r in requests.unique()}  # при нескольких заявках — последняя


async def vms_out(session: AsyncSession, vms: list[VirtualMachine]) -> list[ExecutorVmOut]:
    by_vm = await _vm_requests(session, vms)
    rows = []
    for vm in vms:
        row = ExecutorVmOut.model_validate(vm)
        if req := by_vm.get(vm.id):
            row.request_key, row.request_status, row.request_error = req.issue_key, req.status, req.error
            row.request_url = agent_url(req.issue_key) if req.issue_key else None
            row.request_done = req.status_category == "done"
        rows.append(row)
    return rows


async def list_vm_checks(session: AsyncSession) -> list[ExecutorVmOut]:
    """ВМ, созданные в vSphere и ждущие проверки исполнителем: давние выше."""
    rows = await session.scalars(
        select(VirtualMachine).where(VirtualMachine.status == VmStatus.checking)
        .order_by(VirtualMachine.created_at, VirtualMachine.id).limit(LIST_LIMIT)
    )
    return await vms_out(session, list(rows.unique().all()))


async def _lock_checking(session: AsyncSession, vm_id: int) -> VirtualMachine:
    """ВМ на проверке под блокировкой: подтверждение, пересоздание и отклонение не должны гоняться друг с другом."""
    vm = await session.scalar(
        select(VirtualMachine).where(VirtualMachine.id == vm_id).with_for_update(of=VirtualMachine)
        .execution_options(populate_existing=True)
    )
    if vm is None:
        raise NotFound("Виртуалка не найдена")
    if vm.status != VmStatus.checking:
        raise Conflict("ВМ уже не на проверке: её подтвердили, отклонили или удалили")
    return vm


async def confirm_vm(session: AsyncSession, user: User | None, vm_id: int) -> VirtualMachine:
    """Проверка прошла: ВМ становится готовой, заказчик получает уведомление и данные для подключения.

    `user` пуст, если задачу закрыл в Jira тот, кого нет в портале.
    """
    vm = await _lock_checking(session, vm_id)
    now = datetime.now(timezone.utc)
    vm.status, vm.ready_at, vm.checked_at = VmStatus.ready.value, now, now
    vm.checked_by_id = user.id if user else None
    vm.insight_pending = True
    notifications.vm_ready(session, vm)
    await session.commit()
    await notify(f"✅ ВМ **{vm.name}** проверена исполнителем и выдана ({vm.requester_name}, {vm.department.name})")
    return vm


async def recreate_vm(session: AsyncSession, vm_id: int) -> VirtualMachine:
    """Проверка не прошла и ремонт не помог: worker удалит ВМ и создаст её заново под тем же номером и именем."""
    vm = await _lock_checking(session, vm_id)
    vm.status, vm.recreate = VmStatus.deleting.value, True
    await session.commit()
    await notify(f"🔁 ВМ **{vm.name}** пересоздаётся по решению исполнителя ({vm.requester_name}, {vm.department.name})")
    return vm


async def reject_vm(session: AsyncSession, user: User | None, vm_id: int, reason: str, comment: str) -> VirtualMachine:
    """ВМ отклонена при проверке: worker её удалит, номер вернётся в Insight, заказчик увидит причину в уведомлении."""
    vm = await _lock_checking(session, vm_id)
    vm.status, vm.released_at = VmStatus.deleting.value, datetime.now(timezone.utc)  # released_by пуст: имя исполнителя скрыто
    vm.checked_by_id = user.id if user else None
    notifications.vm_rejected(session, vm, reason, comment)
    await session.commit()
    await notify(f"🚫 ВМ **{vm.name}** (заказ №{vm.order_number}) отклонена исполнителем: {reason}")
    return vm


async def list_returns(session: AsyncSession) -> list[Booking]:
    """Вернувшиеся ПК, ждущие очистки диска: давние первыми."""
    return await cleaning.list_waiting(session)


async def confirm_cleaned(session: AsyncSession, user: User | None, booking_id: int) -> Booking:
    """Исполнитель очистил диск вернувшегося ПК: ПК становится свободным, в Insight пишется «Ожидает».

    `user` пуст, если задачу «Возврат ПК» закрыл в Jira тот, кого нет в портале.
    """
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise NotFound("Заказ не найден")
    comp = await session.scalar(
        select(Computer).where(Computer.id == booking.computer_id).with_for_update(of=Computer)
        .execution_options(populate_existing=True)
    )
    if comp.status != ComputerStatus.cleaning:
        raise Conflict(f"{comp.name} не ждёт очистки")
    new_status = status_after_return(comp)
    add_event(
        session,
        computer_id=comp.id,
        booking_id=booking.id,
        actor_id=user.id if user else None,
        event_type=EventType.cleaned,
        from_status=comp.status,
        to_status=new_status,
        message=f"Заказ №{booking.order_number}: диск очищен, ПК свободен",
    )
    comp.status = new_status
    comp.writeback_pending = runtime.current().insight_writeback
    await session.commit()

    await notify(f"🧹 **{comp.name}** очищен и свободен (заказ №{booking.order_number})")
    return await get_booking(session, booking.id)
