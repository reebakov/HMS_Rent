from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.user import User


class ServiceRequest(Base, TimestampMixin):
    """Заявка в Jira Service Desk по компьютеру или виртуалке.

    kind: problem — «Сообщить о проблеме» из «Моей аренды»; return — заявка на возврат ПК; prepare — подготовить ПК
    после брони; build — сборка по запросу (без ПК и ВМ, привязана к команде department_id).
    Статус и комментарии админов берутся из Jira; статус обновляет worker, комментарии — по запросу.
    """

    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    vm_id: Mapped[int | None] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)  # команда сборки
    issue_key: Mapped[str | None] = mapped_column(String(32), index=True)  # например HMS-123
    summary: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(128))  # как в Jira: «Ожидает поддержки», «Решено»…
    status_category: Mapped[str | None] = mapped_column(String(32))  # new / indeterminate / done
    error: Mapped[str | None] = mapped_column(Text)  # короткая причина для сотрудника, если Jira не приняла заявку (подробности — в логе)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")

    @property
    def is_open(self) -> bool:
        return self.issue_key is not None and (self.status_category or "").lower() != "done"
