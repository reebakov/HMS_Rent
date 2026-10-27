"""Мощности кластера vCenter для ВМ: сводка для админки и проверка перед созданием ВМ."""
import asyncio
import logging

from app.core.config import settings
from app.integrations.vsphere import client as vsphere
from app.integrations.vsphere.client import ClusterUsage
from app.schemas.admin import ClusterCapacity

log = logging.getLogger(__name__)

MB_IN_GB = 1024


def shortage(usage: ClusterUsage, ram_gb: int, disk_gb: int) -> str | None:
    """Чего не хватает под ВМ. CPU не проверяем: переподписка по ядрам нормальна, а МГц на vCPU у кластера разные."""
    free_ram = (usage.ram_total_mb - usage.ram_used_mb) / MB_IN_GB
    free_disk = (usage.storage_total_mb - usage.storage_used_mb) / MB_IN_GB
    lacking = []
    if free_ram < ram_gb:
        lacking.append(f"памяти: нужно {ram_gb} ГБ, свободно {free_ram:.0f} ГБ")
    if free_disk < disk_gb:
        lacking.append(f"диска: нужно {disk_gb} ГБ, свободно {free_disk:.0f} ГБ")
    return f"Недостаточно мощностей кластера, не хватает {'; '.join(lacking)}" if lacking else None


async def summary() -> ClusterCapacity:
    if not settings.vsphere_configured:
        return ClusterCapacity(ok=False, error="vCenter не подключён")
    try:
        usage = await asyncio.to_thread(vsphere.cluster_usage)
    except vsphere.VSphereError as exc:
        return ClusterCapacity(ok=False, error=str(exc))
    except Exception:  # сводка не должна ронять страницу
        log.exception("Не удалось получить мощности кластера")
        return ClusterCapacity(ok=False, error="Не удалось получить данные из vCenter")
    return ClusterCapacity(
        ok=True,
        cpu_total_ghz=round(usage.cpu_total_mhz / 1000, 1), cpu_free_ghz=round((usage.cpu_total_mhz - usage.cpu_used_mhz) / 1000, 1),
        ram_total_gb=round(usage.ram_total_mb / MB_IN_GB), ram_free_gb=round((usage.ram_total_mb - usage.ram_used_mb) / MB_IN_GB),
        storage_total_gb=round(usage.storage_total_mb / MB_IN_GB), storage_free_gb=round((usage.storage_total_mb - usage.storage_used_mb) / MB_IN_GB),
    )
