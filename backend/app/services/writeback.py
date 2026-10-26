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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.insight.base import InsightSource
from app.integrations.insight.factory import create_insight_source
from app.models import Booking, BookingStatus, Computer, ComputerStatus, EventType, VirtualMachine
from app.services import runtime
from app.services.events import add_event

log = logging.getLogger(__name__)

RESERVE = "reserve"  # ключ в writeback.status_values: свободный ПК в пуле не из общего


def _in_reserve_pool(comp: Computer) -> bool:
    """Свободный ПК в пуле, отличном от общего (INSIGHT_DEFAULT_POOL): в Insight он «Резерв», а не «Ожидает».
    Без заданного общего пула правило выключено."""
    general = settings.insight_default_pool.strip().lower()
    return bool(general and comp.pool and comp.pool.name.lower() != general)


async def clear_pending(session: AsyncSession, row: Computer | VirtualMachine, flag: str) -> None:
    """Снять флаг очереди, только если строку не меняли с момента чтения.

    Пока состояние уходило в Insight, могла прийти новая бронь или продление и снова поставить флаг: безусловное
    снятие потеряло бы эту правку. Любое изменение строки сдвигает `updated_at`, и тогда флаг остаётся до следующего
    круга. Вызывать до изменения других полей строки: автосброс сессии тоже сдвигает `updated_at`.
    """
    model = type(row)
    await session.execute(
        update(model).where(model.id == row.id, model.updated_at == row.updated_at).values({flag: False})
        .execution_options(synchronize_session=False)
    )


async def push_pending(session: AsyncSession, batch: int = 50) -> int:
    if not (await runtime.load(session)).insight_writeback:
        return 0
    computers = (
        await session.scalars(select(Computer).where(Computer.writeback_pending.is_(True)).order_by(Computer.id).limit(batch))
    ).unique().all()
    if not computers:
        return 0

    source = create_insight_source()
    wb = source.mapping.writeback
    done = 0
    try:
        for comp in computers:
            if comp.status == ComputerStatus.cleaning:
                # на очистке в Insight остаётся «Используется»; запись пойдёт после подтверждения исполнителя
                await clear_pending(session, comp, "writeback_pending")
                continue
            booking = await session.scalar(
                select(Booking).where(Booking.computer_id == comp.id, Booking.status == BookingStatus.active)
            )
            # неисправный ПК (его отметил исполнитель) пишется статусом «ТО», если он задан в маппинге, а не «Ожидает»
            idle = ComputerStatus.maintenance if comp.status == ComputerStatus.maintenance else ComputerStatus.available
            target = ComputerStatus.booked if booking else idle
            status_key = RESERVE if target == ComputerStatus.available and _in_reserve_pool(comp) else target
            values: dict[str, str | None] = {}
            extras: dict[str, str | None] = {}  # необязательные поля: их сбой не должен мешать записи статуса
            if wb.status_attribute and (wb.status_values.get(status_key) or wb.status_values.get(target)):
                values[wb.status_attribute] = wb.status_values.get(status_key) or wb.status_values[target]
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
                    warning = await write_object(source, comp.insight_object_id, comp.insight_object_type_id,
                                                 values, extras, wb.status_attribute)
                await clear_pending(session, comp, "writeback_pending")
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


async def write_object(source: InsightSource, object_id: int, type_id: int | None, values: dict, extras: dict,
                       status_attribute: str | None) -> str | None:
    """Пишет значения в объект Insight. Возвращает предупреждение, если статус записан, а доп. поля — нет."""
    try:
        await source.update_object(object_id, type_id, values, optional=set(extras))
        return None
    except Exception as exc:  # noqa: BLE001
        if not extras or status_attribute not in values:
            raise
        # доп. поле не прошло (например, у атрибута тип «Select» без такого значения) — статус всё равно пишем
        await source.update_object(object_id, type_id, {status_attribute: values[status_attribute]})
        return f"Статус записан, но поля аренды (пул / команда / срок / номер заказа) — нет: {str(exc)[:300]}"
