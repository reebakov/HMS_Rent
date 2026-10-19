from datetime import date, datetime

from pydantic import Field, field_validator

from app.core import clock
from app.schemas.common import ComputerShort, DepartmentShort, InputModel, ORMModel, UserShort


class BookingCreate(InputModel):
    computer_id: int
    department_id: int
    requester_name: str = Field(min_length=2, max_length=255)
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: date | None = None

    @field_validator("expected_return_at")
    @classmethod
    def not_in_past(cls, value: date | None) -> date | None:
        if value is not None and value < clock.today():
            raise ValueError("Дата возврата не может быть в прошлом")
        return value


class BookingReturn(InputModel):
    comment: str | None = Field(default=None, max_length=2000)


class BookingOut(ORMModel):
    id: int
    order_number: int
    status: str
    computer: ComputerShort
    department: DepartmentShort
    user: UserShort
    requester_name: str
    requester_nick: str
    purpose: str | None
    booked_at: datetime
    expected_return_at: date | None
    returned_at: datetime | None
    returned_by: UserShort | None
    return_comment: str | None
