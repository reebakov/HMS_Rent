"""Раздел «Исполнитель»: очередь выданных ПК и данные для подключения, которые исполнитель вносит после подготовки.

Первый этап интерфейса исполнителя (DR-15075): заявка Service Desk «подготовить ПК» остаётся задачей для исполнителя
и ведёт на страницу заказа, а результат вносится в портале, и заказчик видит его в «Моей аренде».
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.models import Booking, BookingStatus, EventType, User
from app.schemas.booking import ExecutorResult
from app.services import notifications
from app.services.bookings import get_booking
from app.services.events import add_event

LIST_LIMIT = 200


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
