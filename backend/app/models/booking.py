from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.computer import Computer
from app.models.department import Department
from app.models.enums import BookingStatus
from app.models.user import User


class Booking(Base, TimestampMixin):
    """Бронирование: какой ПК, за каким отделом, кто взял, когда взял и когда вернул."""

    __tablename__ = "bookings"
    __table_args__ = (
        # На уровне БД: у компьютера не может быть двух активных бронирований
        Index(
            "uq_bookings_active_computer",
            "computer_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    computer_id: Mapped[int] = mapped_column(ForeignKey("computers.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    requester_name: Mapped[str] = mapped_column(String(255))
    requester_nick: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str | None] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(16), index=True, default=BookingStatus.active.value)
    booked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expected_return_at: Mapped[date | None] = mapped_column(Date)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    return_comment: Mapped[str | None] = mapped_column(Text)

    computer: Mapped[Computer] = relationship(lazy="joined")
    department: Mapped[Department] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    returned_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[returned_by_id])
