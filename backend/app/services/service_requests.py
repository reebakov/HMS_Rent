"""Заявки в Jira Service Desk по ПК и виртуалкам: «Сообщить о проблеме» и заявка на возврат ПК."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import DomainError, Forbidden, NotFound
from app.integrations import servicedesk as sd
from app.models import Booking, ServiceRequest, User, VirtualMachine

log = logging.getLogger(__name__)

REFRESH_EVERY = timedelta(minutes=2)


def _can_access(user: User, owner_id: int, department_id: int) -> bool:
    return user.is_admin or owner_id == user.id or (user.department_id is not None and user.department_id == department_id)


def _booking_text(b: Booking) -> str:
    c = b.computer
    specs = " · ".join(x for x in (c.cpu, f"{c.ram_gb} ГБ" if c.ram_gb else None, c.storage, c.gpu) if x)
    return "\n".join([
        f"Компьютер: {c.name} ({c.insight_key or 'без ключа'})",
        f"Заказ №{b.order_number}",
        f"Характеристики: {specs or '—'}",
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


async def _send(req: ServiceRequest, request_type_id: int, on_behalf_of: str | None) -> None:
    key, status = await sd.create_request(request_type_id, req.summary, req.description, on_behalf_of)
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
        if not _can_access(user, item.user_id, item.department_id):
            raise Forbidden("Это не ваш компьютер")
        summary = f"HMS Rent: проблема с ПК {item.computer.name} (заказ №{item.order_number})"
        context = _booking_text(item)
    elif vm_id:
        item = await session.get(VirtualMachine, vm_id)
        if item is None:
            raise NotFound("Виртуалка не найдена")
        if not _can_access(user, item.user_id, item.department_id):
            raise Forbidden("Это не ваша виртуалка")
        summary = f"HMS Rent: проблема с ВМ {item.name} (заказ №{item.order_number})"
        context = _vm_text(item)
    else:
        raise DomainError("Укажите компьютер или виртуалку")

    req = ServiceRequest(
        kind="problem", user_id=user.id, booking_id=booking_id, vm_id=vm_id, summary=summary,
        description=f"{message}\n\n---\n{context}\nОбращение отправил: {user.display_name} ({user.email or user.username})",
    )
    try:
        await _send(req, settings.sd_request_type_problem, user.username)
    except sd.ServiceDeskError as exc:
        raise DomainError(f"Не удалось создать заявку: {exc}") from exc
    session.add(req)
    await session.commit()
    return req


async def create_return(session: AsyncSession, booking_id: int, actor: User) -> None:
    """Заявка «Возврат ПК» после возврата на сайте. Ошибка не мешает возврату — сохраняется в заявке."""
    if not (settings.service_desk_configured and settings.sd_return_on_return):
        return
    b = await session.get(Booking, booking_id)
    if b is None:
        return
    req = ServiceRequest(
        kind="return", user_id=actor.id, booking_id=b.id,
        summary=f"HMS Rent: возврат ПК {b.computer.name} (заказ №{b.order_number})",
        description=_booking_text(b) + (f"\nКомментарий при возврате: {b.return_comment}" if b.return_comment else "")
        + f"\nВернул: {actor.display_name} ({actor.email or actor.username})",
    )
    try:
        await _send(req, settings.sd_request_type_return, actor.username)
    except sd.ServiceDeskError as exc:
        log.warning("Заявка на возврат %s не создана: %s", b.computer.name, exc)
        req.error = str(exc)[:1000]
    session.add(req)
    await session.commit()


def _visible_to(user: User):
    """Условие доступа к заявке: своя или заявка по ПК и виртуалкам команды."""
    team_bookings = select(Booking.id).where(Booking.department_id == user.department_id)
    team_vms = select(VirtualMachine.id).where(VirtualMachine.department_id == user.department_id)
    cond = ServiceRequest.user_id == user.id
    if user.department_id:
        cond = or_(cond, ServiceRequest.booking_id.in_(team_bookings), ServiceRequest.vm_id.in_(team_vms))
    return cond


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


async def get_with_comments(session: AsyncSession, user: User, request_id: int) -> tuple[ServiceRequest, list]:
    req = await _get_accessible(session, user, request_id)
    if not req.issue_key:
        return req, []
    try:
        status = await sd.get_status(req.issue_key)
        req.status, req.status_category = status.status, status.category
        req.last_checked_at = datetime.now(timezone.utc)
        await session.commit()
        comments = await sd.get_comments(req.issue_key)
    except sd.ServiceDeskError as exc:
        raise DomainError(f"Jira недоступна: {exc}") from exc
    return req, comments


async def add_comment(session: AsyncSession, user: User, request_id: int, text: str) -> None:
    req = await _get_accessible(session, user, request_id)
    if not req.issue_key:
        raise DomainError("Заявка не была создана в Jira")
    try:
        await sd.add_comment(req.issue_key, user.display_name, text)
    except sd.ServiceDeskError as exc:
        raise DomainError(f"Не удалось отправить сообщение: {exc}") from exc


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
        try:
            status = await sd.get_status(req.issue_key)
            req.status, req.status_category = status.status, status.category
        except sd.ServiceDeskError as exc:
            log.warning("Статус %s не обновлён: %s", req.issue_key, exc)
        req.last_checked_at = datetime.now(timezone.utc)
    await session.commit()
