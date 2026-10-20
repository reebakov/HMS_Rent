"""Фоновая обработка виртуалок (вызывает worker): создание, удаление, обновление IP."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.notify import notify
from app.integrations.vsphere import client as vsphere
from app.models import VirtualMachine, VmStatus
from app.services import capacity, runtime

log = logging.getLogger(__name__)

CREATE_ATTEMPTS = 2  # первая попытка + одна повторная (регламент DR-15065)
CREATE_RETRY_DELAY_SEC = 10  # пауза перед повтором: vCenter успевает освободить имя и отпустить задачу


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)  # отдельная функция — в тестах подменяется, чтобы не ждать по-настоящему


def _annotation(vm: VirtualMachine) -> str:
    created = vm.ready_at or datetime.now(timezone.utc)  # при обновлении срока «Создана» не должна меняться
    until = f"{vm.expected_return_at:%d.%m.%Y}" if vm.expected_return_at else "без срока"
    lines = [
        "HMS Rent — виртуалка выдана через портал",
        f"Арендатор: {vm.requester_name} ({vm.requester_nick}), {vm.user.email or vm.user.username}",
        f"Отдел: {vm.department.name}",
        f"Создана: {created:%d.%m.%Y %H:%M} UTC",
        f"Вернуть до: {until}",
    ]
    if vm.purpose:
        lines.append(f"Цель: {vm.purpose}")
    return "\n".join(lines)


async def _notify_failed(vm: VirtualMachine) -> None:
    """Исполнители узнают об ошибке из канала: в портале её видит только заказчик в карточке ВМ."""
    await notify(f"⚠️ ВМ **{vm.name}** не создана для {vm.requester_name} ({vm.department.name}): {(vm.error or '')[:300]}")


async def _fail(session: AsyncSession, vm: VirtualMachine, error: str) -> bool:
    vm.status, vm.error, vm.insight_pending = VmStatus.failed.value, error, True  # номер вернётся в Insight
    await session.commit()
    await _notify_failed(vm)
    return True


async def _cluster_shortage(vm: VirtualMachine) -> str | None:
    """Не хватает ли в кластере памяти или диска под ВМ. Если vCenter не отвечает, создаём как обычно: ошибку даст клон."""
    try:
        usage = await asyncio.to_thread(vsphere.cluster_usage)
    except Exception:  # noqa: BLE001
        log.warning("Не удалось проверить мощности кластера перед созданием ВМ %s", vm.name, exc_info=True)
        return None
    return capacity.shortage(usage, vm.ram_gb, vm.disk_gb)


async def _take(session: AsyncSession, status: VmStatus) -> VirtualMachine | None:
    """Одна задача из очереди; SKIP LOCKED — два worker'а не возьмут одну ВМ."""
    return await session.scalar(
        select(VirtualMachine).where(VirtualMachine.status == status)
        .order_by(VirtualMachine.id).limit(1).with_for_update(skip_locked=True, of=VirtualMachine)
    )


async def create_next(session: AsyncSession) -> bool:
    vm = await _take(session, VmStatus.queued)
    if vm is None:
        return False
    vm.status = VmStatus.creating.value
    await session.commit()
    template, spec = None, None  # заявки до введения шаблонов (template_key пуст) идут по настройкам из .env
    if vm.template_key:
        tmpl = next((t for t in runtime.current().vm_templates if t.key == vm.template_key), None)
        if tmpl is None or not tmpl.template:
            # шаблон убрали из настроек после постановки в очередь: клон из шаблона по умолчанию дал бы не ту ОС
            return await _fail(session, vm, f"Шаблон ОС «{vm.os_label or vm.template_key}» больше не доступен")
        template, spec = tmpl.template, tmpl.customization_spec
    if problem := await _cluster_shortage(vm):
        return await _fail(session, vm, problem)
    annotated_until = vm.expected_return_at  # срок попадёт в Notes; если его продлят во время клона, upkeep обновит
    annotation = _annotation(vm)
    for attempt in range(1, CREATE_ATTEMPTS + 1):
        try:
            info = await asyncio.to_thread(
                vsphere.create_vm, vm.name, vm.cpu, vm.ram_gb, vm.disk_gb, annotation, template, spec,
            )
        except Exception as exc:  # noqa: BLE001
            # недоделанный клон vSphere-клиент убирает сам; по имени здесь не удаляем — оно может быть чужим
            log.exception("Не удалось создать ВМ %s (попытка %d из %d)", vm.name, attempt, CREATE_ATTEMPTS)
            vm.error = str(exc)[:1000]
            if attempt < CREATE_ATTEMPTS:
                await _pause(CREATE_RETRY_DELAY_SEC)
            continue
        vm.status, vm.error = VmStatus.ready.value, None
        vm.notes_return_at = annotated_until
        vm.insight_pending = True  # в Insight известен IP
        vm.vsphere_moid, vm.ip_address, vm.power_state = info.moid, info.ip_address, info.power_state
        vm.ready_at = datetime.now(timezone.utc)
        await notify(f"🖥 ВМ **{vm.name}** создана для {vm.requester_name} ({vm.department.name})")
        break
    else:
        return await _fail(session, vm, vm.error or "Не удалось создать ВМ")  # error — ошибка последней попытки
    await session.commit()
    return True


async def delete_next(session: AsyncSession) -> bool:
    vm = await _take(session, VmStatus.deleting)
    if vm is None:
        return False
    try:
        if vm.vsphere_moid:  # без moid в vCenter нечего удалять: ВМ не создавалась, а по имени искать нельзя
            await asyncio.to_thread(vsphere.delete_vm, vm.vsphere_moid)
        vm.status, vm.deleted_at, vm.error = VmStatus.deleted.value, datetime.now(timezone.utc), None
        vm.insight_pending = True  # номер освободится в Insight
    except Exception as exc:  # noqa: BLE001 — оставляем в deleting, повторим на следующем круге
        log.exception("Не удалось удалить ВМ %s", vm.name)
        vm.error = str(exc)[:1000]
    await session.commit()
    return True


async def refresh_ips(session: AsyncSession, batch: int = 10) -> None:
    """IP появляется, когда Windows загрузилась и VMware Tools отчитались."""
    vms = (await session.scalars(
        select(VirtualMachine).where(VirtualMachine.status == VmStatus.ready, VirtualMachine.ip_address.is_(None))
        .limit(batch)
    )).unique().all()
    for vm in vms:
        try:
            info = await asyncio.to_thread(vsphere.vm_status, vm.vsphere_moid) if vm.vsphere_moid else None
        except Exception:  # noqa: BLE001
            continue
        if info:
            if info.ip_address != vm.ip_address:
                vm.insight_pending = True
            vm.ip_address, vm.power_state = info.ip_address, info.power_state
    await session.commit()


async def recover(session: AsyncSession) -> None:
    """После перезапуска worker'а: «creating» без результата — проверить vSphere и вернуть в очередь."""
    for vm in (await session.scalars(select(VirtualMachine).where(VirtualMachine.status == VmStatus.creating))).unique():
        info = await asyncio.to_thread(vsphere.find_vm, vm.name)
        if info:
            vm.status, vm.vsphere_moid, vm.ready_at = VmStatus.ready.value, info.moid, datetime.now(timezone.utc)
        else:
            vm.status = VmStatus.queued.value
    await session.commit()


async def create_pending(session: AsyncSession) -> None:
    """Создаёт ВМ из очереди по одной, пока она не опустеет. Клон идёт до часа, поэтому у очереди свой цикл воркера."""
    while await create_next(session):
        pass


async def refresh_annotations(session: AsyncSession, batch: int = 10) -> None:
    """Продление меняет срок заказа, а в Notes ВМ в vCenter остаётся прежний: перезаписываем описание."""
    vms = (await session.scalars(
        select(VirtualMachine).where(
            VirtualMachine.status == VmStatus.ready, VirtualMachine.vsphere_moid.is_not(None),
            VirtualMachine.notes_return_at.is_distinct_from(VirtualMachine.expected_return_at),
        ).order_by(VirtualMachine.id).limit(batch)
    )).unique().all()
    for vm in vms:
        try:
            await asyncio.to_thread(vsphere.set_annotation, vm.vsphere_moid, _annotation(vm))
        except Exception:  # noqa: BLE001 — повторим на следующем круге
            log.warning("Не удалось обновить описание ВМ %s в vCenter", vm.name, exc_info=True)
            continue
        vm.notes_return_at = vm.expected_return_at
    await session.commit()


async def upkeep(session: AsyncSession, deletions: int = 5) -> None:
    """Удаление ВМ, подтягивание IP и срока в Notes. Отдельно от создания: долгий клон не задерживает удаления."""
    for _ in range(deletions):  # удаления с ошибкой повторятся на следующем круге, а не в бесконечном цикле
        if not await delete_next(session):
            break
    await refresh_ips(session)
    await refresh_annotations(session)
