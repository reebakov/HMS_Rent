"""Настройки, которые админ меняет на сайте (Админка → «Настройки»).

По умолчанию берутся из .env, правки с сайта хранятся в таблице app_settings и важнее .env.
Кэш на 5 секунд: API и worker видят изменения почти сразу, база не нагружается.
"""
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AppSetting
from app.schemas.settings import RuntimeConfig, SettingsOut


def _defaults() -> RuntimeConfig:
    return RuntimeConfig(
        insight_sync_interval_min=max(1, settings.insight_sync_interval_sec // 60),
        insight_writeback=settings.insight_writeback,
        vm_enabled=settings.vsphere_configured,
    )


_cache: tuple[float, RuntimeConfig] = (0.0, _defaults())


def settings_out(config: RuntimeConfig) -> SettingsOut:
    """Настройки с сайта плюс то, что задано только в .env и показывается админу."""
    return SettingsOut(**config.model_dump(), vsphere_configured=settings.vsphere_configured,
                       vcenter_host=settings.vcenter_host)


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
