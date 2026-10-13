from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.department import Department

# Какие отделы видят пул. Нет ни одной строки — пул виден всем сотрудникам.
pool_departments = Table(
    "pool_departments",
    Base.metadata,
    Column("pool_id", ForeignKey("pools.id", ondelete="CASCADE"), primary_key=True),
    Column("department_id", ForeignKey("departments.id", ondelete="CASCADE"), primary_key=True),
)


class Pool(Base, TimestampMixin):
    """Пул выдачи — набор компьютеров, который админы открывают сотрудникам.

    В каталоге видны только ПК из опубликованных пулов. Если у пула указаны отделы —
    его видят только сотрудники этих отделов. ПК без пула видит только админ.
    """

    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(default=True)

    departments: Mapped[list[Department]] = relationship(secondary=pool_departments, lazy="selectin")
