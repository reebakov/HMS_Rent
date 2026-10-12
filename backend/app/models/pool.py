from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Pool(Base, TimestampMixin):
    """Пул выдачи — набор компьютеров, который админы открывают сотрудникам.

    В каталоге видны только ПК из опубликованных пулов. ПК без пула видит только админ.
    """

    __tablename__ = "pools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_published: Mapped[bool] = mapped_column(default=True)
