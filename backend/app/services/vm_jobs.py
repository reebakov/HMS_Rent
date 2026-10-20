"""Фоновая обработка виртуалок (вызывает worker): создание, удаление, обновление IP."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.notify import notify
from app.integrations.vsphere import client as vsphere
from app.models import VirtualMachine, VmStatus
from app.services import runtime

log = logging.getLogger(__name__)

CREATE_ATTEMPTS = 2  # первая попытка + одна повторная (регламент DR-15065)
CREATE_RETRY_DELAY_SEC = 10  # пауза перед повтором: vCenter успевает освободить имя и отпустить задачу


async def _pause(seconds: float) -> None:
    await asyncio.sleep(seconds)  # отдельная функция — в тестах подменяется, чтобы не ждать по-настоящему


def _annotation(vm: VirtualMachine) -> str:
    until = f"{vm.expected_return_at:%d.%m.%Y}" if vm.expected_return_at else "без срока"
    lines = [
        "HMS Rent — виртуалка выдана через портал",
        f"Арендатор: {vm.requester_name} ({vm.requester_nick}), {vm.user.email or vm.user.username}",
        f"Отдел: {vm.department.name}",
        f"Создана: {datetime.now(timezone.utc):%d.%m.%Y %H:%M} UTC",
        f"Вернуть до: {until}",
    ]
    if vm.purpose:
        lines.append(f"Цель: {vm.purpose}")
    return "\n".join(lines)


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
            vm.status, vm.error = VmStatus.failed.value, f"Шаблон ОС «{vm.os_label or vm.template_key}» больше не доступен"
            await session.commit()
            return True
        template, spec = tmpl.template, tmpl.customization_spec
    for attempt in range(1, CREATE_ATTEMPTS + 1):
        try:
            info = await asyncio.to_thread(
                vsphere.create_vm, vm.name, vm.cpu, vm.ram_gb, vm.disk_gb, _annotation(vm), template, spec,
            )
        except Exception as exc:  # noqa: BLE001
            # недоделанный клон vSphere-клиент убирает сам; по имени здесь не удаляем — оно может быть чужим
            log.exception("Не удалось создать ВМ %s (попытка %d из %d)", vm.name, attempt, CREATE_ATTEMPTS)
            vm.error = str(exc)[:1000]
            if attempt < CREATE_ATTEMPTS:
                await _pause(CREATE_RETRY_DELAY_SEC)
            continue
        vm.status, vm.error = VmStatus.ready.value, None
        vm.vsphere_moid, vm.ip_address, vm.power_state = info.moid, info.ip_address, info.power_state
        vm.ready_at = datetime.now(timezone.utc)
        await notify(f"🖥 ВМ **{vm.name}** создана для {vm.requester_name} ({vm.department.name})")
        break
    else:
        vm.status = VmStatus.failed.value  # в error осталась ошибка последней попытки
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


async def run_once(session: AsyncSession) -> None:
    if not settings.vsphere_configured:
        return
    for _ in range(2):  # за один круг — не больше двух клонов, чтобы не забить vCenter
        if not await create_next(session):
            break
    for _ in range(5):  # удаления с ошибкой повторятся на следующем круге, а не в бесконечном цикле
        if not await delete_next(session):
            break
    await refresh_ips(session)
