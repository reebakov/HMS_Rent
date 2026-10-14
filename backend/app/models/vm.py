from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.department import Department
from app.models.user import User


class AppSetting(Base):
    """Настройки, которые админ меняет на сайте (страница «Настройки»). Перекрывают значения из .env."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


class VirtualMachine(Base, TimestampMixin):
    """Виртуалка из конструктора: клон шаблона в vSphere, закреплённый за сотрудником.

    Жизненный цикл (поле status): queued → creating → ready → deleting → deleted;
    при ошибке — failed (текст в error). Создание и удаление выполняет worker.
    """

    __tablename__ = "virtual_machines"
    __table_args__ = (
        # одно имя не может быть у двух «живых» виртуалок
        Index("uq_virtual_machines_alive_name", "name", unique=True,
              postgresql_where=text("status NOT IN ('deleted', 'failed')")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)  # имя в vSphere (с префиксом)
    cpu: Mapped[int]
    ram_gb: Mapped[int]
    disk_gb: Mapped[int]
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    error: Mapped[str | None] = mapped_column(Text)

    order_number: Mapped[int] = mapped_column(unique=True)  # сквозной номер заказа (общий с бронями ПК), с 1

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    requester_name: Mapped[str] = mapped_column(String(255))
    requester_nick: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str | None] = mapped_column(Text)
    expected_return_at: Mapped[date | None] = mapped_column(Date)

    vsphere_moid: Mapped[str | None] = mapped_column(String(64))  # id ВМ в vCenter, например vm-1234
    ip_address: Mapped[str | None] = mapped_column(String(64))
    power_state: Mapped[str | None] = mapped_column(String(32))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда попросили удалить
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    department: Mapped[Department] = relationship(lazy="joined")
    released_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[released_by_id])
