from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.db.base import Base, TimestampMixin


class Department(Base, TimestampMixin):
    """Справочник отделов. Выбирается из списка, чтобы в отчётах не было «QA», «qa» и «Отдел QA»."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(64))
    head_name: Mapped[str | None] = mapped_column(String(255))  # руководитель отдела
    is_active: Mapped[bool] = mapped_column(default=True)

    @property
    def is_executors(self) -> bool:
        """Отдел исполнителей (код `EXECUTORS_DEPARTMENT_CODE`; пусто — правило выключено): его сотрудники — исполнители."""
        code = settings.executors_department_code.strip().lower()
        return bool(code and (self.code or "").strip().lower() == code)
