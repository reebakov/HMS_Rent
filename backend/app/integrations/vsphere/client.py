"""Работа с vCenter через pyVmomi: клон шаблона, настройка, включение, удаление.

Все функции синхронные (pyVmomi блокирующий) — сервис вызывает их через asyncio.to_thread.
"""
import logging
import ssl
import time
from contextlib import contextmanager
from dataclasses import dataclass

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

from app.core.config import settings

log = logging.getLogger(__name__)


class VSphereError(Exception):
    pass


@dataclass
class ClusterUsage:
    """Сводка использования кластера из vCenter: CPU в МГц, память и хранилище в МБ."""
    cpu_total_mhz: int
    cpu_used_mhz: int
    ram_total_mb: int
    ram_used_mb: int
    storage_total_mb: int
    storage_used_mb: int


@dataclass
class VmInfo:
    moid: str
    name: str
    power_state: str
    ip_address: str | None


@contextmanager
def connect():
    if not settings.vsphere_configured:
        raise VSphereError("vCenter не настроен: задайте VCENTER_HOST, VCENTER_USER, VCENTER_PASSWORD")
    kwargs = {}
    if not settings.vcenter_verify_ssl:
        kwargs["sslContext"] = ssl._create_unverified_context()  # noqa: SLF001 — самоподписанный сертификат
    try:
        si = SmartConnect(host=settings.vcenter_host, user=settings.vcenter_user,
                          pwd=settings.vcenter_password, **kwargs)
    except vim.fault.InvalidLogin as exc:
        raise VSphereError("vCenter: неверный логин или пароль сервисной учётки") from exc
    except Exception as exc:  # noqa: BLE001
        raise VSphereError(f"vCenter недоступен: {exc}") from exc
    try:
        yield si
    finally:
        Disconnect(si)


def _find(si, vimtype, name: str, root=None):
    view = si.content.viewManager.CreateContainerView(root or si.content.rootFolder, [vimtype], True)
    try:
        return next((obj for obj in view.view if obj.name == name), None)
    finally:
        view.Destroy()


def _wait(task, what: str, timeout: int = 1800):
    started = time.monotonic()
    while task.info.state in (vim.TaskInfo.State.queued, vim.TaskInfo.State.running):
        if time.monotonic() - started > timeout:
            raise VSphereError(f"{what}: превышено время ожидания")
        time.sleep(2)
    if task.info.state != vim.TaskInfo.State.success:
        raise VSphereError(f"{what}: {task.info.error.msg if task.info.error else 'ошибка'}")
    return task.info.result


def _cluster(si):
    dc = _find(si, vim.Datacenter, settings.vcenter_datacenter)
    if dc is None:
        raise VSphereError(f"Не найден датацентр «{settings.vcenter_datacenter}»")
    cluster = _find(si, vim.ClusterComputeResource, settings.vcenter_cluster, dc.hostFolder)
    if cluster is None:
        raise VSphereError(f"Не найден кластер «{settings.vcenter_cluster}»")
    return dc, cluster


def _placement(si, template_name: str | None = None):
    dc, cluster = _cluster(si)
    # vApp — тоже ResourcePool, поэтому ищем среди пулов кластера
    pool = _find(si, vim.ResourcePool, settings.vcenter_resource_pool, cluster)
    if pool is None:
        raise VSphereError(f"В кластере нет vApp/пула «{settings.vcenter_resource_pool}»")
    folder = dc.vmFolder
    for part in filter(None, settings.vcenter_folder.split("/")):
        folder = next((f for f in folder.childEntity if isinstance(f, vim.Folder) and f.name == part), None)
        if folder is None:
            raise VSphereError(f"Не найдена папка «{settings.vcenter_folder}»")
    template_name = template_name or settings.vcenter_template_windows
    template = _find(si, vim.VirtualMachine, template_name, dc.vmFolder)
    if template is None:
        raise VSphereError(f"Не найден шаблон «{template_name}»")
    return dc, pool, folder, template


def check(template_names: list[str] | None = None) -> dict:
    """Проверка настроек без изменений в vSphere (для кнопки в админке и CLI)."""
    with connect() as si:
        dc, pool, folder, template = _placement(si)
        disk = next(d for d in template.config.hardware.device if isinstance(d, vim.vm.device.VirtualDisk))
        return {
            "vcenter": settings.vcenter_host,
            "datacenter": dc.name,
            "pool": f"{pool.name} ({'vApp' if isinstance(pool, vim.VirtualApp) else 'пул ресурсов'})",
            "folder": folder.name,
            "template": template.name,
            "template_cpu": template.config.hardware.numCPU,
            "template_ram_gb": template.config.hardware.memoryMB // 1024,
            "template_disk_gb": disk.capacityInKB // (1024 * 1024),
            # все шаблоны ОС из настроек: найдены ли они в vCenter
            "templates": {n: _find(si, vim.VirtualMachine, n, dc.vmFolder) is not None for n in (template_names or [])},
        }


def cluster_usage() -> ClusterUsage:
    """Занятые и свободные мощности кластера, в котором создаются ВМ."""
    with connect() as si:
        _, cluster = _cluster(si)
        usage = cluster.GetResourceUsage()
        return ClusterUsage(
            cpu_total_mhz=usage.cpuCapacityMHz, cpu_used_mhz=usage.cpuUsedMHz,
            ram_total_mb=usage.memCapacityMB, ram_used_mb=usage.memUsedMB,
            storage_total_mb=usage.storageCapacityMB, storage_used_mb=usage.storageUsedMB,
        )


def find_vm(name: str) -> VmInfo | None:
    with connect() as si:
        vm = _find(si, vim.VirtualMachine, name)
        return _info(vm) if vm else None


def _info(vm) -> VmInfo:
    return VmInfo(moid=vm._moId, name=vm.name, power_state=str(vm.runtime.powerState),  # noqa: SLF001
                  ip_address=vm.guest.ipAddress if vm.guest else None)


def create_vm(name: str, cpu: int, ram_gb: int, disk_gb: int, annotation: str,
              template_name: str | None = None, customization_spec: str | None = None) -> VmInfo:
    """Клонирует шаблон в vApp/пул, задаёт CPU/RAM/описание, расширяет диск, включает ВМ."""
    with connect() as si:
        if _find(si, vim.VirtualMachine, name):
            raise VSphereError(f"ВМ с именем «{name}» уже есть в vCenter")
        dc, pool, folder, template = _placement(si, template_name)

        relocate = vim.vm.RelocateSpec(pool=pool)
        if settings.vcenter_datastore:
            ds = _find(si, vim.Datastore, settings.vcenter_datastore, dc.datastoreFolder)
            if ds is None:
                raise VSphereError(f"Не найден datastore «{settings.vcenter_datastore}»")
            relocate.datastore = ds
        config = vim.vm.ConfigSpec(numCPUs=cpu, numCoresPerSocket=cpu, memoryMB=ram_gb * 1024,
                                   annotation=annotation)
        spec = vim.vm.CloneSpec(location=relocate, config=config, powerOn=False, template=False)
        spec_name = settings.vcenter_customization_spec if customization_spec is None else customization_spec
        if spec_name:
            item = si.content.customizationSpecManager.GetCustomizationSpec(spec_name)
            custom = item.spec
            if isinstance(custom.identity, vim.vm.customization.Sysprep):
                # имя компьютера в Windows = имя ВМ (не длиннее 15 символов)
                custom.identity.userData.computerName = vim.vm.customization.FixedName(name=name[:15])
            elif isinstance(custom.identity, vim.vm.customization.LinuxPrep):
                custom.identity.hostName = vim.vm.customization.FixedName(name=name[:63])  # hostname в Linux
            spec.customization = custom

        log.info("vSphere: клонирую %s → %s (%s CPU, %s ГБ RAM, %s ГБ диск)",
                 template.name, name, cpu, ram_gb, disk_gb)
        vm = _wait(template.CloneVM_Task(folder=folder, name=name, spec=spec), "Клонирование", timeout=3600)
        try:
            _finish_setup(vm, disk_gb)
        except Exception:
            # клон уже наш: убираем его по объекту, а не по имени, чтобы не задеть чужую ВМ
            _destroy(vm)
            raise
        return _info(vm)


def _finish_setup(vm, disk_gb: int) -> None:
    """Диск (только увеличение), сетевая карта подключается при включении, включение ВМ."""
    changes = []
    for dev in vm.config.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualDisk) and disk_gb * 1024 * 1024 > dev.capacityInKB:
            dev.capacityInKB = disk_gb * 1024 * 1024
            changes.append(vim.vm.device.VirtualDeviceSpec(operation="edit", device=dev))
        elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
            dev.connectable.startConnected = True
            dev.connectable.connected = True
            changes.append(vim.vm.device.VirtualDeviceSpec(operation="edit", device=dev))
    if changes:
        _wait(vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(deviceChange=changes)), "Настройка диска и сети")
    _wait(vm.PowerOnVM_Task(), "Включение")


def set_annotation(moid: str, annotation: str) -> None:
    """Заменяет Notes ВМ (арендатор, отдел, срок). Ошибка vCenter — VSphereError."""
    with connect() as si:
        vm = vim.VirtualMachine(moid, si._stub)  # noqa: SLF001
        _wait(vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(annotation=annotation)), "Обновление описания")


def vm_status(moid: str) -> VmInfo | None:
    with connect() as si:
        vm = vim.VirtualMachine(moid, si._stub)  # noqa: SLF001
        try:
            return _info(vm)
        except vim.fault.ManagedObjectNotFound:
            return None


def _destroy(vm) -> None:
    """Выключает и удаляет ВМ с диска. Уже удалённая — не ошибка."""
    try:
        if vm.runtime.powerState == vim.VirtualMachinePowerState.poweredOn:
            _wait(vm.PowerOffVM_Task(), "Выключение")
        _wait(vm.Destroy_Task(), "Удаление")
    except vim.fault.ManagedObjectNotFound:
        return


def delete_vm(moid: str) -> None:
    """Удаляет ВМ портала по id в vCenter. По имени не ищет: имя могло занять чужая ВМ."""
    with connect() as si:
        _destroy(vim.VirtualMachine(moid, si._stub))  # noqa: SLF001
