"""Определение категории мощности, если в Insight нет своего поля «Категория».

Пороги и шаблоны видеокарт — в .env (TIER_*). Порядок важен: первое совпадение побеждает.
"""
from app.core.config import settings
from app.models.enums import Tier


def _gpu_matches(gpu: str | None, patterns: list[str]) -> bool:
    gpu = (gpu or "").lower()
    return any(p.lower() in gpu for p in patterns)


def classify(*, is_virtual: bool, ram_gb: int | None, gpu: str | None) -> str:
    if is_virtual:
        return Tier.vm.value
    ram = ram_gb or 0
    if ram >= settings.tier_powerful_min_ram_gb or _gpu_matches(gpu, settings.powerful_gpu_patterns):
        return Tier.powerful.value
    if ram >= settings.tier_medium_min_ram_gb or _gpu_matches(gpu, settings.medium_gpu_patterns):
        return Tier.medium.value
    return Tier.weak.value
