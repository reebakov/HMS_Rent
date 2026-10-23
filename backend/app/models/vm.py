from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.department import Department
from app.models.enums import VmStatus
from app.models.user import User

if TYPE_CHECKING:
    from app.models.booking import TermRequest


class AppSetting(Base):
    """Настройки, которые админ меняет на сайте (страница «Настройки»). Перекрывают значения из .env."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)  # как в миграции 0003
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())


VM_LOGIN = "user"  # локальная учётная запись в шаблонах ВМ и на подготовленных ПК; пароль сообщают отдельно
CONNECTION_METHODS = {"windows": "RDP", "linux": "VNC"}


class VirtualMachine(Base, TimestampMixin):
    """Виртуалка из конструктора: клон шаблона в vSphere, закреплённый за сотрудником.

    Жизненный цикл (поле status): queued → creating → checking → ready → deleting → deleted;
    при ошибке — failed (текст в error). Создание и удаление выполняет worker; в checking ВМ проверяет исполнитель
    (подтверждает, пересоздаёт или отклоняет), заказчику данные для подключения до подтверждения не показываются.
    """

    __tablename__ = "virtual_machines"
    __table_args__ = (
        # одно имя не может быть у двух «живых» виртуалок
        Index("uq_virtual_machines_alive_name", "name", unique=True,
              postgresql_where=text("status NOT IN ('deleted', 'failed')")),
        # и один объект Insight (номер ВМ) не может быть у двух живых виртуалок
        Index("uq_virtual_machines_alive_insight_object", "insight_object_id", unique=True,
              postgresql_where=text("insight_object_id IS NOT NULL AND status NOT IN ('deleted', 'failed')")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)  # имя в vSphere (с префиксом)
    cpu: Mapped[int]
    ram_gb: Mapped[int]
    disk_gb: Mapped[int]
    template_key: Mapped[str | None] = mapped_column(String(32))  # ключ шаблона ОС из настроек (win10, ubuntu2204…)
    os_label: Mapped[str | None] = mapped_column(String(64))  # «Windows 10» — для отображения
    os: Mapped[str | None] = mapped_column(String(16))  # windows / linux — от него зависит способ подключения
    status: Mapped[str] = mapped_column(String(16), index=True, default=VmStatus.queued.value)
    error: Mapped[str | None] = mapped_column(Text)

    order_number: Mapped[int] = mapped_column(unique=True)  # сквозной номер заказа (общий с бронями ПК), с 1

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    requester_name: Mapped[str] = mapped_column(String(255))
    requester_nick: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str | None] = mapped_column(Text)
    expected_return_at: Mapped[date | None] = mapped_column(Date)

    vsphere_moid: Mapped[str | None] = mapped_column(String(64))  # id ВМ в vCenter, например vm-1234
    insight_object_id: Mapped[int | None]  # объект Insight типа Virtual: его имя (A1###) стало именем ВМ
    insight_object_type_id: Mapped[int | None]
    insight_pending: Mapped[bool] = mapped_column(default=False, server_default=text("false"))  # записать в Insight
    notes_return_at: Mapped[date | None] = mapped_column(Date)  # срок, записанный сейчас в Notes ВМ в vCenter
    ip_address: Mapped[str | None] = mapped_column(String(64))
    power_state: Mapped[str | None] = mapped_column(String(32))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда стала доступна заказчику
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда исполнитель подтвердил проверку
    checked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    recreate: Mapped[bool] = mapped_column(default=False, server_default=text("false"))  # после удаления создать заново
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # когда попросили удалить
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    department: Mapped[Department] = relationship(lazy="joined")
    released_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[released_by_id])
    pending_term_request: Mapped["TermRequest | None"] = relationship(
        primaryjoin="and_(VirtualMachine.id == TermRequest.vm_id, TermRequest.status == 'pending')",
        lazy="selectin", viewonly=True,
    )

    @property
    def connection_login(self) -> str:
        return VM_LOGIN

    @property
    def connection_method(self) -> str | None:
        return CONNECTION_METHODS.get(self.os or "")

    @property
    def requested_return_at(self) -> date | None:
        """Срок, о котором арендатор просит дольше лимита и который ещё не согласован."""
        return self.pending_term_request.requested_return_at if self.pending_term_request else None
