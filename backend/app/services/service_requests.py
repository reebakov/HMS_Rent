"""Заявки в Jira Service Desk: «Сообщить о проблеме», возврат ПК, подготовка ПК после брони и сборка по запросу."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.integrations import servicedesk as sd
from app.integrations.servicedesk import portal_url
from app.models import Booking, BookingStatus, ServiceRequest, ServiceRequestKind, User, VirtualMachine
from app.schemas.service_request import BuildCreate, RequestOut
from app.services import departments, notifications, runtime, term_limit
from app.services.access import ensure_access, mine_or_team
from app.services.orders import next_order_number, requester_name

log = logging.getLogger(__name__)

REFRESH_EVERY = timedelta(minutes=2)


def request_out(req: ServiceRequest) -> RequestOut:
    row = RequestOut.model_validate(req)
    row.url = portal_url(req.issue_key) if req.issue_key else None
    return row


def _booking_text(b: Booking) -> str:
    c = b.computer
    specs = " · ".join(x for x in (c.cpu, f"{c.ram_gb} ГБ" if c.ram_gb else None, c.storage, c.gpu) if x)
    return "\n".join([
        f"Компьютер: {c.name} ({c.insight_key or 'без ключа'})",
        f"Заказ №{b.order_number}",
        f"Характеристики: {specs or '—'}",
        *([f"ОС: {b.os_label}"] if b.os_label else []),
        f"Команда-получатель: {b.department.name}",
        f"Арендатор: {b.requester_name} ({b.requester_nick}), {b.user.email or b.user.username}",
        f"Взят: {b.booked_at:%d.%m.%Y}" + (f", вернуть до {b.expected_return_at:%d.%m.%Y}" if b.expected_return_at else ""),
    ])


def _vm_text(vm: VirtualMachine) -> str:
    return "\n".join([
        f"Виртуалка: {vm.name} ({vm.os_label or 'ОС не указана'})",
        f"Заказ №{vm.order_number}",
        f"Ресурсы: {vm.cpu} CPU · {vm.ram_gb} ГБ · {vm.disk_gb} ГБ, IP: {vm.ip_address or '—'}, статус: {vm.status}",
        f"Команда-получатель: {vm.department.name}",
        f"Арендатор: {vm.requester_name} ({vm.requester_nick}), {vm.user.email or vm.user.username}",
    ])


def _jira_summary(summary: str) -> str:
    """Тема заявки в Jira: с префиксом SD_SUMMARY_PREFIX («ТЕСТ» при проверках), в портале — без него."""
    prefix = settings.sd_summary_prefix.strip()
    return f"{prefix} {summary}" if prefix else summary


async def _send(req: ServiceRequest, request_type_id: int, on_behalf_of: str | None,
                extra_fields: dict | None = None) -> None:
    key, status = await sd.create_request(request_type_id, _jira_summary(req.summary), req.description, on_behalf_of,
                                          extra_fields)
    req.issue_key, req.status, req.status_category = key, status.status, status.category
    req.error, req.last_checked_at = None, datetime.now(timezone.utc)


async def create_problem(session: AsyncSession, user: User, *, booking_id: int | None, vm_id: int | None,
                         message: str) -> ServiceRequest:
    if not settings.service_desk_configured:
        raise DomainError("Заявки в Service Desk пока не подключены — напишите в HMS")
    if booking_id:
        item = await session.get(Booking, booking_id)
        if item is None:
            raise NotFound("Бронирование не найдено")
        ensure_access(user, item.user_id, item.department_id, "Это не ваш компьютер")
        summary = f"HMS Rent: проблема с ПК {item.computer.name} (заказ №{item.order_number})"
        context = _booking_text(item)
    elif vm_id:
        item = await session.get(VirtualMachine, vm_id)
        if item is None:
            raise NotFound("Виртуалка не найдена")
        ensure_access(user, item.user_id, item.department_id, "Это не ваша виртуалка")
        summary = f"HMS Rent: проблема с ВМ {item.name} (заказ №{item.order_number})"
        context = _vm_text(item)
    else:
        raise DomainError("Укажите компьютер или виртуалку")

    req = ServiceRequest(
        kind=ServiceRequestKind.problem.value, user_id=user.id, booking_id=booking_id, vm_id=vm_id, summary=summary,
        description=f"{message}\n\n---\n{context}\nОбращение отправил: {user.display_name} ({user.email or user.username})",
    )
    try:
        await _send(req, settings.sd_request_type_problem, user.username, settings.sd_problem_fields)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка по проблеме не создана: %s", exc)  # подробности Jira — только в лог
        raise DomainError(f"Не удалось создать заявку: {exc.user_message}") from exc
    session.add(req)
    await session.commit()
    return req


async def _save_in_background(session: AsyncSession, req: ServiceRequest, request_type_id: int, actor: User) -> None:
    """Заявка, которую сервис создаёт сам после операции: ошибка Jira операцию не отменяет и сохраняется в заявке."""
    try:
        await _send(req, request_type_id, actor.username)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка «%s» не создана: %s", req.summary, exc)
        req.error = exc.user_message  # поле видно сотруднику в карточке заявки; подробности — только в логе
    session.add(req)
    await session.commit()


async def create_return(session: AsyncSession, booking_id: int, actor: User) -> None:
    """Заявка «Возврат ПК» после возврата на сайте."""
    if not (settings.service_desk_configured and settings.sd_return_on_return):
        return
    b = await session.get(Booking, booking_id)
    if b is None:
        return
    await _save_in_background(session, ServiceRequest(
        kind=ServiceRequestKind.return_.value, user_id=actor.id, booking_id=b.id,
        summary=f"HMS Rent: возврат ПК {b.computer.name} (заказ №{b.order_number})",
        description=_booking_text(b) + (f"\nКомментарий при возврате: {b.return_comment}" if b.return_comment else "")
        + f"\nВернул: {actor.display_name} ({actor.email or actor.username})",
    ), settings.sd_request_type_return, actor)


async def create_diagnose(session: AsyncSession, booking_id: int, actor: User, comment: str) -> None:
    """Заявка «Диагностика комплекта» после того, как исполнитель отметил ПК неисправным.

    К заказу не привязана: заказ отклонён, а заявка нужна исполнителям, не заказчику и его команде.
    """
    if not settings.service_desk_configured:
        return
    b = await session.get(Booking, booking_id)
    if b is None:
        return
    await _save_in_background(session, ServiceRequest(
        kind=ServiceRequestKind.diagnose.value, user_id=actor.id,
        summary=f"HMS Rent: диагностика комплекта {b.computer.name}",
        description=f"ПК выведен из пула как неисправный (заказ №{b.order_number}, отклонён).\n"
                    f"Комментарий исполнителя: {comment}\nОтметил: {actor.display_name} ({actor.email or actor.username})\n\n"
                    "Переведите ПК в Insight в «ТО», если запись в Insight в портале выключена, проведите диагностику и "
                    "после ремонта верните ПК в пул.\n\n" + _booking_text(b),
    ), settings.sd_request_type_order, actor)


async def create_prepare(session: AsyncSession, booking_id: int, actor: User) -> None:
    """Заявка «подготовить ПК» после брони: исполнитель ставит выбранную ОС и настраивает ПК (до задач DR-15072)."""
    if not (settings.service_desk_configured and settings.sd_prepare_on_booking):
        return
    b = await session.get(Booking, booking_id)
    if b is None:
        return
    await _save_in_background(session, ServiceRequest(
        kind=ServiceRequestKind.prepare.value, user_id=actor.id, booking_id=b.id,
        summary=f"HMS Rent: подготовить ПК {b.computer.name} (заказ №{b.order_number})",
        description="Поставить выбранную ОС, выполнить первичную настройку и внести данные для подключения "
        f"на странице заказа: {settings.public_url.rstrip('/')}/executor/orders/{b.id}\n\n"
        + _booking_text(b) + (f"\nЦель: {b.purpose}" if b.purpose else ""),
    ), settings.sd_request_type_order, actor)


async def create_build(session: AsyncSession, user: User, data: BuildCreate) -> ServiceRequest:
    """Сборка по запросу: заявка исполнителям с номером заказа; собранный ПК выдаётся вне портала (до DR-15075)."""
    if not settings.service_desk_configured:
        raise DomainError("Заявки в Service Desk пока не подключены — напишите в HMS")
    cfg = await runtime.load(session)
    if data.build and data.build not in cfg.pc_builds:
        raise DomainError("Такой типовой сборки нет в списке — обновите страницу")
    if data.os_label not in cfg.pc_os_list:
        raise DomainError("Такой ОС нет в списке — обновите страницу")
    dept = await departments.for_order(session, user, data.department_id)
    _, longer = term_limit.plan(user, data.expected_return_at)

    order_number = await next_order_number(session)
    variant = f"тип {data.build.split(' — ')[0]}" if data.build else "своя конфигурация"
    lines = [
        f"Сборка: {data.build}" if data.build else f"Своя конфигурация: {data.custom}",
        f"ОС: {data.os_label}",
        f"Заказ №{order_number}",
        f"Команда-получатель: {dept.name}",
        f"Арендатор: {requester_name(user)} ({data.requester_nick}), {user.email or user.username}",
        f"Срок аренды: до {data.expected_return_at:%d.%m.%Y}"
        + (" — дольше 3 месяцев, нужно согласование администратора" if longer else ""),
        *([f"Желаемый срок готовности: {data.wanted_by:%d.%m.%Y}"] if data.wanted_by else []),
        *([f"Цель: {data.purpose}"] if data.purpose else []),
    ]
    req = ServiceRequest(
        kind=ServiceRequestKind.build.value, user_id=user.id, department_id=dept.id,
        summary=f"HMS Rent: сборка ПК — {variant} (заказ №{order_number})",
        description="Проверить комплектующие, собрать и настроить ПК, завести его в Insight и выдать заказчику.\n\n"
        + "\n".join(lines),
    )
    try:
        await _send(req, settings.sd_request_type_order, user.username)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка на сборку не создана: %s", exc)
        raise DomainError(f"Не удалось создать заявку: {exc.user_message}") from exc
    session.add(req)
    await session.commit()
    return req


def _visible_to(user: User):
    """Условие доступа к заявке: своя, сборка команды или заявка по ПК и виртуалкам пользователя и его команды."""
    bookings = select(Booking.id).where(mine_or_team(user, Booking.user_id, Booking.department_id))
    vms = select(VirtualMachine.id).where(mine_or_team(user, VirtualMachine.user_id, VirtualMachine.department_id))
    return or_(mine_or_team(user, ServiceRequest.user_id, ServiceRequest.department_id),
               ServiceRequest.booking_id.in_(bookings), ServiceRequest.vm_id.in_(vms))


async def list_for_user(session: AsyncSession, user: User) -> list[ServiceRequest]:
    """Свои заявки и заявки команды (по её ПК и виртуалкам)."""
    stmt = select(ServiceRequest).where(_visible_to(user)).order_by(ServiceRequest.created_at.desc()).limit(200)
    return list((await session.scalars(stmt)).unique().all())


async def _get_accessible(session: AsyncSession, user: User, request_id: int) -> ServiceRequest:
    req = await session.get(ServiceRequest, request_id)
    if req is None:
        raise NotFound("Заявка не найдена")
    # Проверка в SQL по одной заявке, а не по списку list_for_user: тот обрезан 200 строками, и старые заявки
    # автора считались бы чужими
    if not user.is_admin and await session.scalar(
        select(ServiceRequest.id).where(ServiceRequest.id == request_id, _visible_to(user))
    ) is None:
        raise Forbidden("Нет доступа к заявке")
    return req


async def _sync_status(req: ServiceRequest) -> None:
    """Статус заявки из Jira и то, что нужно для статуса заказчику; ошибка самого статуса — наружу.

    История, резолюция и комментарий — дополнительные чтения REST Jira: если у сервисной учётки нет прав, статус
    всё равно обновляется, а заказчик видит название из Jira.
    """
    status = await sd.get_status(req.issue_key)
    req.status, req.status_category = status.status, status.category
    req.last_checked_at = datetime.now(timezone.utc)
    try:
        if req.status in ("Backlog", "To Do") and not req.was_taken or req.status_category == "done" and req.resolution is None:
            details = await sd.get_details(req.issue_key)
            req.was_taken = req.was_taken or details.taken
            req.resolution = details.resolution
        req.status_note = await _last_staff_comment(req.issue_key) if req.status == "Frozen" else None
    except sd.ServiceDeskError as exc:
        log.warning("Заявка %s: история и комментарий не получены: %s", req.issue_key, exc)


async def _close_if_settled(session: AsyncSession, req: ServiceRequest) -> None:
    """Задачу «подготовить ПК» закрывает портал: Done, когда исполнитель внёс данные подключения, Rejected, когда
    заказ отклонён или отменён до подготовки. Закрытие вручную не мешает: уже закрытую задачу портал пропускает.

    Делает это worker, а не обработчики запросов: при недоступной Jira закрытие просто повторится в следующий круг.
    """
    if req.kind != ServiceRequestKind.prepare.value or req.booking_id is None or req.status_category == "done":
        return
    booking = await session.get(Booking, req.booking_id)
    if booking.prepared_at is not None:
        resolution = sd.RESOLUTION_DONE
    elif booking.status != BookingStatus.active:
        resolution = sd.RESOLUTION_REJECTED
    else:
        return
    try:
        await sd.close_issue(req.issue_key, resolution)
        await _sync_status(req)
    except sd.ServiceDeskError as exc:
        log.warning("Задача %s не закрыта (%s): %s", req.issue_key, resolution, exc)


async def _last_staff_comment(issue_key: str) -> str | None:
    comments = [c for c in await sd.get_comments(issue_key) if not c.from_portal]
    return comments[-1].body if comments else None


async def is_untouched(session: AsyncSession, booking_id: int) -> bool:
    """Задача «подготовить ПК» по заказу ещё в Backlog, значит, заказ можно отменить (DR-15072).

    False — задачи нет (Service Desk выключен, заявка не создалась) или она закрыта: возврат обычный. Исполнитель уже
    взял заказ — Conflict. Статус читается из Jira; если проверить не удалось, отмена отклоняется: иначе можно
    отменить заказ, который уже в работе.
    """
    if not settings.service_desk_configured:
        return False
    req = await session.scalar(
        select(ServiceRequest).where(ServiceRequest.kind == ServiceRequestKind.prepare.value,
                                     ServiceRequest.booking_id == booking_id, ServiceRequest.issue_key.is_not(None))
        .order_by(ServiceRequest.id.desc()).limit(1)
    )
    if req is None:
        return False
    try:
        await _sync_status(req)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка %s: статус перед отменой заказа не получен: %s", req.issue_key, exc)
        raise DomainError("Не удалось проверить, взял ли исполнитель заказ: Service Desk недоступен. "
                          "Попробуйте через несколько минут") from exc
    await session.commit()
    if req.status_category == "done":
        return False
    if req.status != "Backlog":
        raise Conflict("Исполнитель уже взял заказ в работу, отменить его нельзя. Дождитесь подготовки ПК и верните его")
    return True


async def get_with_comments(session: AsyncSession, user: User, request_id: int) -> tuple[ServiceRequest, list]:
    req = await _get_accessible(session, user, request_id)
    if not req.issue_key:
        return req, []
    try:
        await _sync_status(req)
        await session.commit()
        comments = await sd.get_comments(req.issue_key)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка %s: статус и комментарии не получены: %s", req.issue_key, exc)
        raise DomainError(exc.user_message) from exc
    return req, comments


async def add_comment(session: AsyncSession, user: User, request_id: int, text: str) -> None:
    req = await _get_accessible(session, user, request_id)
    if not req.issue_key:
        raise DomainError("Заявка не была создана в Jira")
    try:
        await sd.add_comment(req.issue_key, user.display_name, text)
    except sd.ServiceDeskError as exc:
        log.warning("Комментарий к заявке %s не отправлен: %s", req.issue_key, exc)
        raise DomainError(f"Не удалось отправить сообщение: {exc.user_message}") from exc


async def refresh_open(session: AsyncSession, batch: int = 20) -> None:
    """Worker: обновить статусы незакрытых заявок (раз в 2 минуты на каждую)."""
    if not settings.service_desk_configured:
        return
    border = datetime.now(timezone.utc) - REFRESH_EVERY
    rows = (await session.scalars(
        select(ServiceRequest)
        .where(ServiceRequest.issue_key.is_not(None),
               or_(ServiceRequest.status_category.is_(None), ServiceRequest.status_category != "done"),
               or_(ServiceRequest.last_checked_at.is_(None), ServiceRequest.last_checked_at < border))
        .order_by(ServiceRequest.last_checked_at.nulls_first()).limit(batch)
    )).unique().all()
    for req in rows:
        old = req.customer_status
        try:
            await _sync_status(req)
            await _close_if_settled(session, req)
            notifications.request_status(session, req, old)
        except sd.ServiceDeskError as exc:
            log.warning("Статус %s не обновлён: %s", req.issue_key, exc)
            req.last_checked_at = datetime.now(timezone.utc)
    await session.commit()
