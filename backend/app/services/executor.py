"""Раздел «Исполнитель»: очередь выданных ПК и данные для подключения, которые исполнитель вносит после подготовки.

Первый этап интерфейса исполнителя (DR-15075): заявка Service Desk «подготовить ПК» остаётся задачей для исполнителя
и ведёт на страницу заказа, а результат вносится в портале, и заказчик видит его в «Моей аренде».
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.db.session import SessionLocal
from app.integrations.notify import notify
from app.models import Booking, BookingStatus, Computer, ComputerStatus, EventType, User
from app.schemas.booking import FAULTY_REASON, ExecutorReject, ExecutorResult
from app.services import notifications, runtime, service_requests
from app.services.bookings import get_booking, status_after_return
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


async def reject_order(session: AsyncSession, user: User, booking_id: int, data: ExecutorReject) -> Booking:
    """Исполнитель отклоняет заказ ПК: бронь закрывается как cancelled, ПК освобождается, заказчик видит причину.

    «Сервер неисправен» дополнительно выводит ПК из пула и ставит ему статус «Обслуживание»; заявку «Диагностика
    комплекта» создаёт маршрут в фоне. Имя исполнителя остаётся только в журнале ПК: заказчику оно не показывается.
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
    faulty = data.reason == FAULTY_REASON

    booking.status = BookingStatus.cancelled.value
    booking.returned_at = datetime.now(timezone.utc)
    booking.return_comment = f"{data.reason}: {data.comment}"  # returned_by не заполняем: заказчик не должен видеть исполнителя
    new_status = ComputerStatus.maintenance.value if faulty else status_after_return(comp)
    add_event(
        session,
        computer_id=comp.id,
        booking_id=booking.id,
        actor_id=user.id,
        event_type=EventType.rejected,
        from_status=comp.status,
        to_status=new_status,
        message=f"Заказ №{booking.order_number} отклонён: {data.reason}. {data.comment}"
                + (" ПК выведен из пула." if faulty else ""),
    )
    comp.status = new_status
    comp.department_id = None
    comp.usage_until = None
    comp.order_number = None
    if faulty:
        comp.pool_id = None
    comp.writeback_pending = runtime.current().insight_writeback
    notifications.order_rejected(session, booking, data.reason, data.comment)
    await session.commit()

    await notify(f"🚫 Заказ №{booking.order_number} на **{comp.name}** отклонён исполнителем: {data.reason}")
    return await get_booking(session, booking.id)


async def create_diagnose_request(booking_id: int, user_id: int, comment: str) -> None:
    """Заявка «Диагностика комплекта» в Service Desk — в фоне, после отметки «Сервер неисправен»."""
    async with SessionLocal() as session:
        actor = await session.get(User, user_id)
        if actor is not None:
            await service_requests.create_diagnose(session, booking_id, actor, comment)
