"""Бронирование и возврат компьютеров."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Forbidden, NotFound
import logging

from app.db.session import SessionLocal
from app.integrations.insight.factory import create_insight_source, get_mapping
from app.integrations.insight.mapping import map_object
from app.integrations.notify import notify
from app.models import Booking, BookingStatus, Computer, ComputerStatus, Department, EventType, User
from app.schemas.booking import BookingCreate
from app.services.events import add_event
from app.services.orders import next_order_number
from app.services import runtime, service_requests
from app.services.pools import pool_visible
from app.services.writeback import push_pending

log = logging.getLogger(__name__)


async def get_booking(session: AsyncSession, booking_id: int) -> Booking:
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).execution_options(populate_existing=True)
    )
    if booking is None:
        raise NotFound("Бронирование не найдено")
    return booking


def status_after_return(comp: Computer) -> str:
    """Во что превращается ПК после возврата — решает статус в Insight."""
    mapping = get_mapping()
    insight = mapping.status_map.get((comp.insight_status or "").lower(), mapping.default_status)
    if insight == ComputerStatus.in_use and runtime.current().insight_writeback:
        return ComputerStatus.available.value  # «занят» в Insight поставили мы сами — сейчас вернём «свободен»
    return insight


async def _fresh_from_insight(comp: Computer):
    """Статус ПК в Insight «прямо сейчас». None — проверить не удалось (бронь не блокируем)."""
    if comp.insight_object_id is None or comp.writeback_pending:
        return None  # если наши изменения ещё не доехали до Insight, его статус заведомо устаревший
    source = None
    try:
        source = create_insight_source()
        obj = await source.get_object(comp.insight_object_id)
        return map_object(obj, source.mapping) if obj else None
    except Exception as exc:  # noqa: BLE001 — недоступный Insight (или не задан JIRA_URL) не должен ломать бронь
        log.warning("Не удалось перепроверить %s в Insight: %s", comp.name, exc)
        return None
    finally:
        if source is not None:
            await source.close()


async def create_booking(session: AsyncSession, user: User, data: BookingCreate) -> Booking:
    # FOR UPDATE: два человека не смогут одновременно забронировать один ПК
    comp = await session.scalar(
        select(Computer).where(Computer.id == data.computer_id).with_for_update(of=Computer)
    )
    if comp is None or comp.is_archived:
        raise NotFound("Компьютер не найден")
    if not pool_visible(comp.pool, user):
        raise NotFound("Этот компьютер сейчас не выдаётся")
    if comp.status != ComputerStatus.available:
        raise Conflict(f"{comp.name} уже занят или недоступен")
    fresh = await _fresh_from_insight(comp)
    if fresh is not None and fresh.status != ComputerStatus.available:
        # в Jira ПК успели занять руками, а синхронизация ещё не дошла — обновляем и не даём бронировать
        comp.insight_status, comp.status = fresh.insight_status, fresh.status
        await session.commit()
        raise Conflict(f"{comp.name} уже занят в Insight (статус «{fresh.insight_status}»)")
    dept = await session.get(Department, data.department_id)
    if dept is None or not dept.is_active:
        raise NotFound("Отдел не найден")

    order_number = await next_order_number(session)  # берём номер в последнюю очередь, чтобы не плодить пропуски
    booking = Booking(
        computer_id=comp.id,
        department_id=dept.id,
        user_id=user.id,
        order_number=order_number,
        requester_name=data.requester_name,
        requester_nick=data.requester_nick,
        purpose=data.purpose or None,
        expected_return_at=data.expected_return_at,
        status=BookingStatus.active.value,
    )
    session.add(booking)
    comp.status = ComputerStatus.booked.value
    comp.department_id = dept.id
    comp.usage_until = data.expected_return_at
    comp.order_number = order_number
    comp.writeback_pending = runtime.current().insight_writeback
    try:
        await session.flush()
        add_event(
            session,
            computer_id=comp.id,
            booking_id=booking.id,
            actor_id=user.id,
            event_type=EventType.booked,
            from_status=ComputerStatus.available.value,
            to_status=ComputerStatus.booked.value,
            message=f"Заказ №{order_number}. Закреплён за отделом «{dept.name}»: {booking.requester_name} ({booking.requester_nick})",
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Conflict(f"{comp.name} только что забронировали") from exc

    await notify(f"🖥 **{comp.name}** забронирован (заказ №{order_number}): {dept.name}, {booking.requester_name} ({booking.requester_nick})")
    return await get_booking(session, booking.id)


async def return_booking(session: AsyncSession, user: User, booking_id: int, comment: str | None) -> Booking:
    booking = await session.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update(of=Booking)
    )
    if booking is None:
        raise NotFound("Бронирование не найдено")
    if booking.user_id != user.id and not user.is_admin:
        raise Forbidden("Вернуть ПК может тот, кто его бронировал, или администратор")
    if booking.status != BookingStatus.active:
        raise Conflict("Бронирование уже закрыто")
    comp = await session.scalar(
        select(Computer).where(Computer.id == booking.computer_id).with_for_update(of=Computer)
    )

    booking.status = BookingStatus.returned.value
    booking.returned_at = datetime.now(timezone.utc)
    booking.returned_by_id = user.id
    booking.return_comment = (comment or "").strip() or None
    new_status = status_after_return(comp)
    add_event(
        session,
        computer_id=comp.id,
        booking_id=booking.id,
        actor_id=user.id,
        event_type=EventType.returned,
        from_status=comp.status,
        to_status=new_status,
        message=f"Заказ №{booking.order_number} закрыт. Возвращён отделом «{booking.department.name}»" + (f": {booking.return_comment}" if booking.return_comment else ""),
    )
    comp.status = new_status
    comp.department_id = None
    comp.usage_until = None
    comp.order_number = None
    comp.writeback_pending = runtime.current().insight_writeback
    await session.commit()

    await notify(f"↩️ **{comp.name}** возвращён (заказ №{booking.order_number}, {booking.department.name})")
    return await get_booking(session, booking.id)


async def list_user_bookings(session: AsyncSession, user: User) -> list[Booking]:
    rows = await session.scalars(
        select(Booking).where(Booking.user_id == user.id).order_by(Booking.booked_at.desc()).limit(200)
    )
    return list(rows.unique().all())


# Фоновые задачи после ответа: сессия запроса к этому моменту уже закрыта, поэтому у задач своя.

async def push_to_insight() -> None:
    """Сразу после брони/возврата отправляем статус в Insight, не дожидаясь круга воркера."""
    async with SessionLocal() as session:
        await push_pending(session)


async def create_return_request(booking_id: int, user_id: int) -> None:
    """Заявка «Возврат ПК» в Service Desk — в фоне, чтобы не задерживать возврат."""
    async with SessionLocal() as session:
        actor = await session.get(User, user_id)
        if actor is not None:
            await service_requests.create_return(session, booking_id, actor)
