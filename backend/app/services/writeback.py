"""Обратная запись в Insight (включается INSIGHT_WRITEBACK=true).

Работает как очередь «отправь текущее состояние»: у ПК ставится флаг writeback_pending,
воркер отправляет в Insight актуальное состояние и снимает флаг. Операция идемпотентна —
повтор после сбоя Insight ничего не испортит.

Что пишем (имена атрибутов — в insight_mapping.yaml):
* статус — главное, без него запись считается неудавшейся;
* «Пул выдачи» — пул, в котором лежит ПК на портале;
* «Команда-получатель», «Срок использования», «Номер заказа» — из активной брони; у свободного ПК очищаются.
Если дополнительные поля записать не удалось (нет атрибута, не подходит тип), статус всё равно записывается,
а ошибка остаётся видна админу в «Инвентаризации» — один неверный атрибут не блокирует работу портала.
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.insight.base import InsightSource
from app.integrations.insight.factory import create_insight_source
from app.models import Booking, BookingStatus, Computer, ComputerStatus, EventType
from app.services import runtime
from app.services.events import add_event

log = logging.getLogger(__name__)


async def push_pending(session: AsyncSession, batch: int = 50) -> int:
    if not (await runtime.load(session)).insight_writeback:
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
            extras: dict[str, str | None] = {}  # необязательные поля: их сбой не должен мешать записи статуса
            if wb.status_attribute and wb.status_values.get(target):
                values[wb.status_attribute] = wb.status_values[target]
            if wb.pool_attribute:
                extras[wb.pool_attribute] = comp.pool.name if comp.pool else None
            if wb.department_attribute:
                extras[wb.department_attribute] = booking.department.name if booking else None
            if wb.owner_attribute:
                extras[wb.owner_attribute] = booking.user.username if booking else None
            if wb.period_attribute:
                extras[wb.period_attribute] = (
                    booking.expected_return_at.isoformat() if booking and booking.expected_return_at else None
                )
            if wb.order_attribute:
                extras[wb.order_attribute] = str(booking.order_number) if booking else None
            values.update(extras)

            try:
                warning = None
                if values and comp.insight_object_id:
                    warning = await _write(source, comp, values, extras, wb.status_attribute)
                comp.writeback_pending = False
                if warning and warning != comp.writeback_error:  # не спамим журнал одной и той же ошибкой
                    add_event(session, computer_id=comp.id, event_type=EventType.writeback_failed, message=warning)
                comp.writeback_error = warning
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


async def _write(source: InsightSource, comp: Computer, values: dict, extras: dict, status_attribute: str | None) -> str | None:
    """Пишет значения в Insight. Возвращает предупреждение, если статус записан, а доп. поля — нет."""
    try:
        await source.update_object(comp.insight_object_id, comp.insight_object_type_id, values, optional=set(extras))
        return None
    except Exception as exc:  # noqa: BLE001
        if not extras or status_attribute not in values:
            raise
        # доп. поле не прошло (например, у атрибута тип «Select» без такого значения) — статус всё равно пишем
        await source.update_object(
            comp.insight_object_id, comp.insight_object_type_id, {status_attribute: values[status_attribute]}
        )
        return f"Статус записан, но поля аренды (пул / команда / срок / номер заказа) — нет: {str(exc)[:300]}"
