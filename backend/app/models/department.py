from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Department(Base, TimestampMixin):
    """Справочник отделов. Выбирается из списка, чтобы в отчётах не было «QA», «qa» и «Отдел QA»."""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(64))
    head_name: Mapped[str | None] = mapped_column(String(255))  # руководитель отдела
    is_active: Mapped[bool] = mapped_column(default=True)
