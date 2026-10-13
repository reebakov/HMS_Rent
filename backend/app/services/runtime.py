"""Настройки, которые админ меняет на сайте (Админка → «Настройки»).

По умолчанию берутся из .env, правки с сайта хранятся в таблице app_settings и важнее .env.
Кэш на 5 секунд: API и worker видят изменения почти сразу, база не нагружается.
"""
import time

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AppSetting


class RuntimeConfig(BaseModel):
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
    for key in changes:
        row = await session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=getattr(config, key)))
        else:
            row.value = getattr(config, key)
    await session.commit()
    _cache = (time.monotonic(), config)
    return config
