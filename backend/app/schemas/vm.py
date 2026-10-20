from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import DepartmentShort, InputModel, ORMModel, ReturnDate, UserShort


class VmCreate(InputModel):
    name: str = Field(min_length=3, max_length=20, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    cpu: int = Field(ge=1, le=64)
    ram_gb: int = Field(ge=1, le=512)
    disk_gb: int = Field(ge=10, le=4096)
    department_id: int
    requester_name: str = Field(min_length=2, max_length=255)
    requester_nick: str = Field(min_length=1, max_length=128)
    purpose: str | None = Field(default=None, max_length=2000)
    expected_return_at: ReturnDate
    template_key: str | None = None  # шаблон ОС; пусто — первый доступный

    @field_validator("name", mode="before")
    @classmethod
    def lower(cls, value: str) -> str:
        return value.lower() if isinstance(value, str) else value


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
    ip_address: str | None
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
    name_prefix: str
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
