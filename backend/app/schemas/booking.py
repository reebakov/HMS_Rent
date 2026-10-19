from datetime import date, datetime

from pydantic import Field

from app.schemas.common import ComputerShort, DepartmentShort, InputModel, ORMModel, ReturnDate, UserShort


class BookingCreate(InputModel):
    computer_id: int
    department_id: int
    requester_name: str = Field(min_length=2, max_length=255)
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: ReturnDate


class BookingReturn(InputModel):
    comment: str | None = Field(default=None, max_length=2000)


class BookingExtend(InputModel):
    expected_return_at: ReturnDate
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
