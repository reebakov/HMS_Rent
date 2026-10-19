"""Настройки с сайта: шаблоны ОС для конструктора ВМ и значения, которые админ меняет без перезапуска."""
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.schemas.common import InputModel


class VmTemplate(InputModel):
    """Шаблон ОС для конструктора. enabled=False — скрыт; без template — показан как «скоро»."""

    key: str = Field(pattern=r"^[a-z0-9_-]{2,32}$")
    label: str = Field(min_length=2, max_length=64)  # как видит пользователь: «Windows 10»
    os: str = Field(default="windows", pattern=r"^(windows|linux)$")
    template: str = ""  # имя шаблона в vCenter (VMs and Templates)
    customization_spec: str = ""  # спецификация гостевой настройки (необязательно)
    min_disk_gb: int = Field(default=50, ge=10, le=4096)  # диск шаблона — меньше не сделать
    enabled: bool = True


def default_templates() -> list[VmTemplate]:
    return [
        VmTemplate(key="win10", label="Windows 10", os="windows", template=settings.vcenter_template_windows,
                   customization_spec=settings.vcenter_customization_spec, min_disk_gb=50),
        VmTemplate(key="win11", label="Windows 11", os="windows", min_disk_gb=64),
        VmTemplate(key="winsrv2022", label="Windows Server 2022", os="windows", min_disk_gb=60),
        VmTemplate(key="ubuntu2204", label="Ubuntu 22.04", os="linux", min_disk_gb=25),
    ]


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # опечатка в ключе PATCH — ошибка, а не молча не сохранённая настройка

    # Синхронизация с Insight
    insight_sync_interval_min: int = Field(default=10, ge=1, le=1440)
    insight_writeback: bool = False
    # Конструктор виртуалок
    vm_enabled: bool = False
    vm_max_per_user: int = Field(default=2, ge=0, le=50)
    vm_min_cpu: int = Field(default=2, ge=1, le=64)
    vm_max_cpu: int = Field(default=8, ge=1, le=64)
    vm_min_ram_gb: int = Field(default=4, ge=1, le=512)
    vm_max_ram_gb: int = Field(default=32, ge=1, le=512)
    vm_min_disk_gb: int = Field(default=50, ge=10, le=4096)  # не меньше диска шаблона
    vm_max_disk_gb: int = Field(default=200, ge=10, le=4096)
    vm_templates: list[VmTemplate] = Field(default_factory=default_templates)
    # Каталог: как часто страница сама обновляет список ПК
    catalog_refresh_sec: int = Field(default=15, ge=5, le=600)


class SettingsOut(RuntimeConfig):
    vsphere_configured: bool
    vcenter_host: str
