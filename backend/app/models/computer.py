from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.department import Department
from app.models.enums import ComputerStatus, Tier
from app.models.pool import Pool


class Computer(Base, TimestampMixin):
    """Локальная копия компьютера из Insight + состояние на портале."""

    __tablename__ = "computers"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- Связь с Insight ---
    insight_object_id: Mapped[int | None] = mapped_column(unique=True)
    insight_object_type_id: Mapped[int | None]
    insight_key: Mapped[str | None] = mapped_column(String(64))
    insight_object_type: Mapped[str | None] = mapped_column(String(128))
    insight_status: Mapped[str | None] = mapped_column(String(128))  # статус как он есть в Insight
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )  # все атрибуты объекта: «на будущее» и для карточки ПК
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_archived: Mapped[bool] = mapped_column(default=False)  # пропал из Insight

    # --- Характеристики ---
    name: Mapped[str] = mapped_column(String(128), index=True)
    hostname: Mapped[str | None] = mapped_column(String(128))
    is_virtual: Mapped[bool] = mapped_column(default=False)
    cpu: Mapped[str | None] = mapped_column(String(255))
    cpu_cores: Mapped[int | None]
    ram_gb: Mapped[int | None]
    storage: Mapped[str | None] = mapped_column(String(255))
    storage_gb: Mapped[int | None]
    gpu: Mapped[str | None] = mapped_column(String(255))
    os: Mapped[str | None] = mapped_column(String(128))
    location: Mapped[str | None] = mapped_column(String(255))
    serial_number: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    # --- Состояние на портале ---
    # tier — итоговая категория (с учётом ручной правки); tier_override — ручная категория от админа
    tier: Mapped[str] = mapped_column(String(16), index=True, default=Tier.medium.value)
    tier_override: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True, default=ComputerStatus.available.value)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("pools.id"), index=True)  # None — не выдаётся
    note: Mapped[str | None] = mapped_column(Text)

    # --- Обратная запись в Insight (очередь по принципу «отправь текущее состояние») ---
    writeback_pending: Mapped[bool] = mapped_column(default=False)
    writeback_error: Mapped[str | None] = mapped_column(Text)

    department: Mapped[Department | None] = relationship(lazy="joined")
    pool: Mapped[Pool | None] = relationship(lazy="joined")
