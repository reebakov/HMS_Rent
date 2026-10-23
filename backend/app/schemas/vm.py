from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.booking import BookingExtend
from app.schemas.common import DepartmentShort, InputModel, ORMModel, ReturnDate, UserShort
from app.schemas.settings import VmSize


class VmCreate(InputModel):
    cpu: int = Field(ge=1, le=64)
    ram_gb: int = Field(ge=1, le=512)
    disk_gb: int = Field(ge=10, le=4096)
    department_id: int | None = None  # админ может указать любой отдел, остальным — свой
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: ReturnDate
    template_key: str | None = None  # шаблон ОС; пусто — первый доступный


class VmExtend(BookingExtend):
    """Продление ВМ: новый срок и необязательная причина — как у брони ПК."""


class VmOut(ORMModel):
    id: int
    order_number: int
    name: str
    cpu: int
    ram_gb: int
    disk_gb: int
    template_key: str | None = None
    os_label: str | None = None
    status: str
    error: str | None
    department: DepartmentShort
    user: UserShort
    requester_name: str
    requester_nick: str
    purpose: str | None
    expected_return_at: date | None
    requested_return_at: date | None  # срок из заявки админу, пока она ждёт решения
    ip_address: str | None
    connection_login: str
    connection_method: str | None  # RDP для Windows, VNC для Linux; пусто, если ОС неизвестна
    power_state: str | None
    created_at: datetime
    ready_at: datetime | None
    released_at: datetime | None
    deleted_at: datetime | None


class VmTemplateOption(BaseModel):
    key: str
    label: str
    os: str  # windows / linux
    min_disk_gb: int
    available: bool  # False — шаблон ещё не настроен (в конструкторе «скоро»)


class VmOptions(BaseModel):
    enabled: bool
    reason: str | None  # почему конструктор недоступен
    template: str
    min_cpu: int
    max_cpu: int
    min_ram_gb: int
    max_ram_gb: int
    min_disk_gb: int
    max_disk_gb: int
    max_per_user: int
    used_by_me: int
    templates: list[VmTemplateOption] = []
    sizes: list[VmSize] = []  # готовые размеры, которые укладываются в лимиты


VM_REJECT_REASONS = ("Не удалось подготовить ВМ", "Недостаточно мощностей кластера", "Заказчик не ответил", "Некорректный заказ")


class ExecutorVmOut(ORMModel):
    """ВМ на проверке у исполнителя: что проверять и задача в Jira, по которой идёт работа."""

    id: int
    order_number: int
    name: str
    cpu: int
    ram_gb: int
    disk_gb: int
    os_label: str | None
    status: str
    ip_address: str | None
    connection_login: str
    connection_method: str | None
    power_state: str | None
    department: DepartmentShort
    user: UserShort
    requester_name: str
    requester_nick: str
    purpose: str | None
    expected_return_at: date | None
    created_at: datetime
    request_key: str | None = None
    request_url: str | None = None
    request_status: str | None = None
    request_error: str | None = None
    request_done: bool = False


class ExecutorVmReject(InputModel):
    """Отклонение ВМ при проверке: основание из списка регламента и обязательный комментарий."""

    reason: Literal[*VM_REJECT_REASONS]
    comment: str = Field(min_length=1, max_length=2000)
