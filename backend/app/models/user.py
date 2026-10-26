from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.department import Department
from app.models.enums import UserRole


class User(Base, TimestampMixin):
    """Пользователь портала.

    * Сотрудники создаются автоматически при первом входе через Bouncer (username = рабочая почта / UPN).
    * Администраторы — локальные учётки с паролем, создаются командой `python -m app.cli create-admin`.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    ad_department: Mapped[str | None] = mapped_column(String(255))  # зарезервировано под отдел из каталога
    auth_source: Mapped[str] = mapped_column(String(16), default="microsoft")  # bouncer / local / dev; microsoft — старые записи и заведённые заранее
    password_hash: Mapped[str | None] = mapped_column(String(255))  # только у локальных учёток
    role: Mapped[str] = mapped_column(String(16), default=UserRole.user.value)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))  # назначает админ
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    department: Mapped[Department | None] = relationship(lazy="joined")

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.admin

    @property
    def sees_all_pools(self) -> bool:
        """Все опубликованные пулы видят администраторы и отдел исполнителей (по коду, `EXECUTORS_DEPARTMENT_CODE`)."""
        return self.is_admin or bool(self.department and self.department.is_executors)

    @property
    def is_executor(self) -> bool:
        """Раздел «Исполнитель» доступен исполнителям и администраторам."""
        return self.role in (UserRole.executor, UserRole.admin)
