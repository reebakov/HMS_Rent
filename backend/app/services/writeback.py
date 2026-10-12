"""Обратная запись в Insight (включается INSIGHT_WRITEBACK=true).

Работает как очередь «отправь текущее состояние»: у ПК ставится флаг writeback_pending,
воркер отправляет в Insight актуальный статус/отдел/владельца и снимает флаг. Операция
идемпотентна — повтор после сбоя Insight ничего не испортит.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.insight.factory import create_insight_source
from app.models import Booking, BookingStatus, Computer, ComputerStatus, EventType
from app.services.events import add_event

log = logging.getLogger(__name__)


async def push_pending(session: AsyncSession, batch: int = 50) -> int:
    if not settings.insight_writeback:
        return 0
    computers = (
        await session.scalars(select(Computer).where(Computer.writeback_pending.is_(True)).limit(batch))
    ).unique().all()
    if not computers:
        return 0

    source = create_insight_source()
    wb = source.mapping.writeback
    done = 0
    try:
        for comp in computers:
            booking = await session.scalar(
                select(Booking).where(Booking.computer_id == comp.id, Booking.status == BookingStatus.active)
            )
            target = ComputerStatus.booked if booking else ComputerStatus.available
            values: dict[str, str | None] = {}
            if wb.status_attribute and wb.status_values.get(target):
                values[wb.status_attribute] = wb.status_values[target]
            if wb.department_attribute:
                values[wb.department_attribute] = booking.department.name if booking else None
            if wb.owner_attribute:
                values[wb.owner_attribute] = booking.user.username if booking else None

            try:
                if values and comp.insight_object_id:
                    await source.update_object(comp.insight_object_id, comp.insight_object_type_id, values)
                comp.writeback_pending = False
                comp.writeback_error = None
                done += 1
            except Exception as exc:  # noqa: BLE001 — оставляем флаг, повторим на следующем цикле
                error = str(exc)[:1000]
                if error != comp.writeback_error:  # не спамим журнал одной и той же ошибкой
                    add_event(
                        session,
                        computer_id=comp.id,
                        event_type=EventType.writeback_failed,
                        message=f"Не удалось обновить Insight: {error}",
                    )
                comp.writeback_error = error
                log.warning("Writeback %s: %s", comp.name, error)
        await session.commit()
    finally:
        await source.close()
    return done
