"""Настройки с сайта: шаблоны ОС для конструктора ВМ и значения, которые админ меняет без перезапуска."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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


class VmSize(InputModel):
    """Готовый размер ВМ: кнопка в конструкторе ставит ядра, память и диск разом."""

    label: str = Field(min_length=1, max_length=32)  # как видит пользователь: «S», «M», «L»
    cpu: int = Field(ge=1, le=64)
    ram_gb: int = Field(ge=1, le=512)
    disk_gb: int = Field(ge=10, le=4096)


def default_vm_sizes() -> list[VmSize]:
    """Базовая ВМ из расчёта мощностей кластера (DR-15063) — 2 ядра, 4 ГБ, 50 ГБ; остальные кратны ей."""
    return [
        VmSize(label="S", cpu=2, ram_gb=4, disk_gb=50),
        VmSize(label="M", cpu=4, ram_gb=8, disk_gb=100),
        VmSize(label="L", cpu=8, ram_gb=16, disk_gb=200),
    ]


# Строки списков в «Настройках»: пробелы по краям обрезаются, пустая строка не проходит
OsName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]
BuildLine = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=300)]


def default_pc_os() -> list[str]:
    """ОС для физических серверов (DR-15064)."""
    return ["Windows 10 22H2", "Windows 11 26H2", "Windows Server 2022", "Windows Server 2025", "Ubuntu 24.04",
            "Ubuntu 26.04", "Debian 12", "Debian 13", "CentOS Stream 9", "CentOS Stream 10"]


def default_pc_builds() -> list[str]:
    """Типовые сборки из складского оборудования (DR-15062): «тип — состав»."""
    return [
        "A — Intel i5-12400F/13400F, 16 ГБ, SSD 480 ГБ, RTX 3050 LP",
        "B — AMD Ryzen 7 3700X, 16 ГБ, SSD 480 ГБ, RTX 3050 LP",
        "C — Intel i5-12400 (встроенная графика), 16 ГБ, SSD 240–256 ГБ",
        "D — Intel i5-12400F/13400F, 16 ГБ, SSD 240–256 ГБ, GTX 1050/1050 Ti/1650",
        "E — Intel 8–9 поколения, 16 ГБ, SSD 240 ГБ",
        "F — Intel 6–7 поколения, 16 ГБ, SSD 120–240 ГБ",
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
    vm_sizes: list[VmSize] = Field(default_factory=default_vm_sizes)
    # Заказ физического ПК: ОС на выбор и типовые сборки
    pc_os_list: list[OsName] = Field(default_factory=default_pc_os)
    pc_builds: list[BuildLine] = Field(default_factory=default_pc_builds)
    # Каталог: как часто страница сама обновляет список ПК
    catalog_refresh_sec: int = Field(default=15, ge=5, le=600)


class SettingsOut(RuntimeConfig):
    vsphere_configured: bool
    vcenter_host: str
