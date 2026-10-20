"""Общий контракт источника данных Insight. Живой клиент и mock реализуют одно и то же."""
from dataclasses import dataclass, field
from typing import Protocol

from app.integrations.insight.mapping import InsightMapping


class InsightError(Exception):
    pass


@dataclass
class InsightObject:
    """Объект Insight в «плоском» виде: имя атрибута -> строковое значение."""

    id: int
    key: str
    label: str
    object_type: str
    object_type_id: int | None = None
    attributes: dict[str, str] = field(default_factory=dict)


class InsightSource(Protocol):
    mode: str
    mapping: InsightMapping

    async def fetch_objects(self, limit: int = 0) -> list[InsightObject]:
        """Все компьютеры/ВМ, попадающие под запрос из маппинга (limit > 0 — только первые N)."""
        ...

    async def fetch_free_vm_objects(self) -> list[InsightObject]:
        """Объекты ВМ «На складе» (запрос vm_free_query): из них портал берёт номер для новой ВМ."""
        ...

    async def get_object(self, object_id: int) -> InsightObject | None:
        """Один объект «прямо сейчас» (None — не найден) — для перепроверки статуса перед бронью."""
        ...

    async def update_object(
        self, object_id: int, object_type_id: int | None, values: dict[str, str | None],
        optional: set[str] | None = None,
    ) -> None:
        """Записать значения атрибутов (по именам атрибутов Insight). Атрибуты из optional, которых нет у типа, пропускаются."""
        ...

    async def close(self) -> None: ...
