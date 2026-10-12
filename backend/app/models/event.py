from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.computer import Computer
from app.models.user import User


class AssetEvent(Base):
    """Журнал всего, что происходило с компьютером: бронь, возврат, смена статуса в Insight, правки админа."""

    __tablename__ = "asset_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None = система/синхронизация
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    from_status: Mapped[str | None] = mapped_column(String(128))
    to_status: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    computer: Mapped[Computer] = relationship(lazy="joined")
    actor: Mapped[User | None] = relationship(lazy="joined")


class SyncRun(Base):
    """Запуск синхронизации с Insight."""

    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running / success / failed
    mode: Mapped[str] = mapped_column(String(16))  # mock / live
    total: Mapped[int] = mapped_column(default=0)
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    archived: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
