from datetime import date, datetime
from ipaddress import IPv4Address
from typing import Literal

from pydantic import Field

from app.schemas.common import ComputerShort, DepartmentShort, InputModel, ORMModel, ReturnDate, UserShort


class BookingCreate(InputModel):
    computer_id: int
    department_id: int | None = None  # админ может указать любой отдел, остальным — свой
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: ReturnDate
    os_label: str | None = Field(default=None, max_length=64)  # из списка ОС в «Настройках»


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
    os_label: str | None
    booked_at: datetime
    expected_return_at: date | None
    requested_return_at: date | None  # срок из заявки админу, пока она ждёт решения
    returned_at: datetime | None
    returned_by: UserShort | None
    return_comment: str | None
    connection_host: str | None  # данные для подключения — от исполнителя (POST /executor/orders/{id}/result)
    connection_ip: str | None
    connection_method: str | None
    connection_login: str | None
    prepared_at: datetime | None


class ExecutorOrderOut(BookingOut):
    """Заказ для исполнителя: заказчику имя исполнителя не показывается, поэтому поле только здесь."""

    prepared_by: UserShort | None
    # заявка Service Desk «подготовить ПК» по этому заказу (если создавалась)
    request_key: str | None = None
    request_url: str | None = None
    request_status: str | None = None
    request_error: str | None = None


REJECT_REASONS = ("Сервер неисправен", "Заказчик не ответил", "Некорректный заказ")
FAULTY_REASON = REJECT_REASONS[0]  # эта причина ещё и выводит ПК из пула


class ExecutorReject(InputModel):
    """Отклонение заказа ПК: основание из списка регламента и обязательный комментарий."""

    reason: Literal[*REJECT_REASONS]
    comment: str = Field(min_length=1, max_length=2000)


class ExecutorResult(InputModel):
    """Результат подготовки ПК: логин `user` и пароль исполнитель не вводит."""

    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]*$")  # A32.ff.local
    ip: IPv4Address
    method: Literal["RDP", "VNC"]
