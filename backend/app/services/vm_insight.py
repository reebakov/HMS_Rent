"""Запись состояния ВМ в её объект Insight (тот, чей номер стал именем ВМ), по флагу insight_pending.

Как и запись ПК, это очередь «отправь текущее состояние»: идемпотентно, повтор после сбоя безопасен. Включается
настройкой insight_writeback. Живая ВМ: статус «Используется», команда, срок, номер заказа, IP. Удалённая или
упавшая: статус «На складе» и пустые поля, но только если объект не занят другой живой ВМ (номер мог уже уйти в новый
заказ).
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.insight.factory import create_insight_source
from app.models import VirtualMachine, VmStatus
from app.services import runtime
from app.services.writeback import clear_pending, write_object

log = logging.getLogger(__name__)

RELEASED = (VmStatus.deleted, VmStatus.failed)


async def _object_in_use(session: AsyncSession, vm: VirtualMachine) -> bool:
    return bool(await session.scalar(
        select(VirtualMachine.id).where(
            VirtualMachine.insight_object_id == vm.insight_object_id, VirtualMachine.id != vm.id,
            VirtualMachine.status.notin_(RELEASED),
        ).limit(1)
    ))


async def push_pending(session: AsyncSession, batch: int = 20) -> int:
    if not (await runtime.load(session)).insight_writeback:
        return 0
    vms = (await session.scalars(
        select(VirtualMachine).where(VirtualMachine.insight_pending.is_(True),
                                     VirtualMachine.insight_object_id.is_not(None))
        .order_by(VirtualMachine.id).limit(batch)
    )).unique().all()
    if not vms:
        return 0
    source = create_insight_source()
    wb, attrs = source.mapping.writeback, source.mapping.attributes
    done = 0
    try:
        for vm in vms:
            released = vm.status in RELEASED
            if released and await _object_in_use(session, vm):
                await clear_pending(session, vm, "insight_pending")  # объект уже у другой ВМ: этой записи делать нельзя
                continue
            status = wb.vm_status_values["free" if released else "taken"]
            extras = {
                attrs.get("team"): None if released else vm.department.name,
                attrs.get("usage_period"): None if released or not vm.expected_return_at else vm.expected_return_at.isoformat(),
                attrs.get("order_number"): None if released else str(vm.order_number),
                attrs.get("ip_address"): None if released else vm.ip_address,
            }
            extras.pop(None, None)  # атрибут не описан в маппинге — нечего писать
            try:
                warning = await write_object(source, vm.insight_object_id, vm.insight_object_type_id,
                                             {wb.status_attribute: status, **extras}, extras, wb.status_attribute)
            except Exception as exc:  # noqa: BLE001 — флаг остаётся, повторим на следующем круге
                log.warning("Запись ВМ %s в Insight: %s", vm.name, str(exc)[:300])
                continue
            if warning:
                log.warning("ВМ %s: %s", vm.name, warning)
            await clear_pending(session, vm, "insight_pending")
            done += 1
        await session.commit()
    finally:
        await source.close()
    return done
