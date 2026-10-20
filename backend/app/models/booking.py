from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.computer import Computer
from app.models.department import Department
from app.models.enums import BookingStatus
from app.models.user import User
from app.models.vm import VirtualMachine


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

    order_number: Mapped[int] = mapped_column(unique=True)  # сквозной номер заказа (общий с виртуалками), с 1

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


class BookingExtension(Base):
    """Продление брони ПК (booking_id) или ВМ (vm_id): срок был → стал.

    Пока админ не отметил «Принято», продление считается новым. Таблица осталась под прежним именем.
    """

    __tablename__ = "booking_extensions"
    __table_args__ = (
        CheckConstraint("(booking_id IS NULL) <> (vm_id IS NULL)", name="one_target"),  # ровно один адресат
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int | None] = mapped_column(ForeignKey("bookings.id"), index=True)
    vm_id: Mapped[int | None] = mapped_column(ForeignKey("virtual_machines.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # кто продлил: арендатор, участник команды или админ
    old_return_at: Mapped[date | None] = mapped_column(Date)  # у старых заказов срока могло не быть
    new_return_at: Mapped[date] = mapped_column(Date)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    booking: Mapped[Booking | None] = relationship(lazy="joined")
    vm: Mapped[VirtualMachine | None] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined", foreign_keys=[user_id])
    acknowledged_by: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[acknowledged_by_id])

    @property
    def kind(self) -> str:
        return "vm" if self.vm_id is not None else "pc"

    @property
    def name(self) -> str:
        """Имя ПК или ВМ, которой продлили срок."""
        return self.vm.name if self.vm is not None else self.booking.computer.name
