"""Настройки, которые админ меняет на сайте (Админка → «Настройки»).

По умолчанию берутся из .env, правки с сайта хранятся в таблице app_settings и важнее .env.
Кэш на 5 секунд: API и worker видят изменения почти сразу, база не нагружается.
"""
import time

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AppSetting
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


def _default_templates() -> list[VmTemplate]:
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
    vm_templates: list[VmTemplate] = Field(default_factory=_default_templates)
    # Каталог: как часто страница сама обновляет список ПК
    catalog_refresh_sec: int = Field(default=15, ge=5, le=600)


def _defaults() -> RuntimeConfig:
    return RuntimeConfig(
        insight_sync_interval_min=max(1, settings.insight_sync_interval_sec // 60),
        insight_writeback=settings.insight_writeback,
        vm_enabled=settings.vsphere_configured,
    )


_cache: tuple[float, RuntimeConfig] = (0.0, _defaults())


def current() -> RuntimeConfig:
    """Последние загруженные настройки (без обращения к базе)."""
    return _cache[1]


async def load(session: AsyncSession, max_age: float = 5.0) -> RuntimeConfig:
    global _cache
    if time.monotonic() - _cache[0] < max_age:
        return _cache[1]
    rows = (await session.scalars(select(AppSetting))).all()
    data = _defaults().model_dump()
    data.update({r.key: r.value for r in rows if r.key in data})
    try:
        config = RuntimeConfig(**data)
    except ValueError:
        config = _defaults()  # битое значение в базе не должно ронять портал
    _cache = (time.monotonic(), config)
    return config


async def update(session: AsyncSession, changes: dict) -> RuntimeConfig:
    global _cache
    merged = (await load(session, max_age=0)).model_dump() | changes
    config = RuntimeConfig(**merged)  # проверка диапазонов до записи
    # Только при правке самого списка: уже сохранённые дубли не должны мешать менять остальные настройки
    keys = [t.key for t in config.vm_templates]
    if "vm_templates" in changes and len(keys) != len(set(keys)):
        raise ValueError("ключи шаблонов ОС должны быть уникальными")
    dumped = config.model_dump()  # JSON-совместимые значения (шаблоны ОС — список словарей)
    for key in changes:
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=dumped[key]))
        else:
            row.value = dumped[key]
    await session.commit()
    _cache = (time.monotonic(), config)
    return config
