from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import Tier
from app.schemas.booking import BookingOut
from app.schemas.common import DepartmentShort, InputModel, ORMModel, ReturnDate, UserShort, reject_explicit_null
from app.schemas.computer import ComputerOut
from app.schemas.vm import VmOut


class SyncRunOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    mode: str
    total: int
    created: int
    updated: int
    archived: int
    error: str | None


class TierStat(BaseModel):
    tier: str
    total: int
    available: int
    booked: int


class StatsOut(BaseModel):
    total: int
    by_status: dict[str, int]
    by_tier: list[TierStat]
    in_pools: int
    active_bookings: int
    departments_using: int
    overdue: int
    issues: int
    last_sync: SyncRunOut | None


class DepartmentUsage(BaseModel):
    department_id: int
    name: str
    code: str | None
    head_name: str | None
    is_active: bool
    active: int
    by_tier: dict[str, int]
    total_bookings: int
    last_booked_at: datetime | None


class OverdueItem(BaseModel):
    kind: str  # pc / vm
    id: int  # booking_id или vm_id
    order_number: int | None
    name: str
    department: str
    requester_name: str
    requester_nick: str
    email: str | None
    taken_at: datetime | None
    due: date
    days: int


class ExtensionOut(ORMModel):
    id: int
    kind: Literal["pc", "vm"]
    name: str  # имя ПК или ВМ
    booking: BookingOut | None  # продление ПК
    vm: VmOut | None  # продление ВМ
    user: UserShort  # кто продлил
    old_return_at: date | None
    new_return_at: date
    comment: str | None
    created_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by: UserShort | None


class TermRequestOut(ORMModel):
    id: int
    kind: Literal["pc", "vm"]
    name: str  # имя ПК или ВМ
    order_number: int
    department: DepartmentShort
    requester_name: str
    requester_nick: str
    user: UserShort  # кто просит: арендатор или участник его команды
    current_return_at: date | None
    requested_return_at: date
    comment: str | None
    created_at: datetime


class TermApprove(InputModel):
    """Согласование заявки: свой срок админа; без него ставится запрошенный."""

    approved_return_at: ReturnDate | None = None


class InventoryBooking(ORMModel):
    id: int
    requester_name: str
    requester_nick: str
    booked_at: datetime
    expected_return_at: date | None
    user: UserShort


class PoolShort(ORMModel):
    id: int
    name: str
    is_published: bool


class InventoryRow(ComputerOut):
    serial_number: str | None
    is_archived: bool
    tier_override: str | None
    note: str | None
    writeback_error: str | None
    usage_until: date | None = None
    order_number: int | None = None
    pool: PoolShort | None = None
    booking: InventoryBooking | None = None
    issues: list[str] = []


class InventoryPage(BaseModel):
    items: list[InventoryRow]
    total: int


class PoolOut(PoolShort):
    description: str | None
    departments: list[DepartmentShort] = []  # пусто — пул видят все сотрудники
    total: int = 0
    available: int = 0
    booked: int = 0


class PoolSave(InputModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_published: bool | None = None
    department_ids: list[int] | None = None  # кто видит пул; [] — все сотрудники

    @model_validator(mode="after")
    def _no_null(self):
        reject_explicit_null(self, "name", "is_published")
        return self


class PoolAssign(InputModel):
    """В пул по id (из таблицы инвентаризации) или списком имён/ключей Insight («A24, A432 …»)."""

    pool_id: int | None  # None — убрать из пулов
    computer_ids: list[int] | None = None
    names: str | None = Field(default=None, max_length=100_000)


class PoolAssignResult(BaseModel):
    updated: int
    not_found: list[str]


class EventComputer(ORMModel):
    id: int
    name: str


class EventOut(ORMModel):
    id: int
    computer: EventComputer
    booking_id: int | None
    event_type: str
    from_status: str | None
    to_status: str | None
    message: str
    actor: UserShort | None
    created_at: datetime


class ComputerAdminUpdate(InputModel):
    """Поля, которые админ может менять на портале. Статус «железа» меняется в Insight."""

    tier_override: Tier | None = None
    note: str | None = Field(default=None, max_length=2000)


class SyncInfoOut(BaseModel):
    mode: str
    jira_url: str
    interval_sec: int
    writeback: bool
    runs: list[SyncRunOut]


class ComputerHistoryOut(BaseModel):
    computer: InventoryRow
    attributes: dict[str, Any]
    bookings: list[BookingOut]
    events: list[EventOut]

class EventPage(BaseModel):
    items: list[EventOut]
    total: int    


class IdleServer(BaseModel):
    id: int
    name: str
    idle_days: int
    idle_since: date  # возврат последней брони или появление ПК в учёте


class IdleServers(BaseModel):
    """ПК опубликованных пулов, которые сейчас свободны, и сколько они стоят невыданными."""
    count: int
    average_days: int
    items: list[IdleServer]  # самые долго простаивающие, не больше IDLE_TOP


class ClusterCapacity(BaseModel):
    """Мощности кластера для ВМ; без vCenter или при сбое — ok=False и причина."""
    ok: bool
    error: str | None = None
    cpu_total_ghz: float = 0
    cpu_free_ghz: float = 0
    ram_total_gb: float = 0
    ram_free_gb: float = 0
    storage_total_gb: float = 0
    storage_free_gb: float = 0
