from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import DepartmentShort, ORMModel


class ComputerOut(ORMModel):
    id: int
    name: str
    hostname: str | None
    insight_key: str | None
    is_virtual: bool
    tier: str
    cpu: str | None
    cpu_cores: int | None
    ram_gb: int | None
    storage: str | None
    storage_gb: int | None
    gpu: str | None
    os: str | None
    location: str | None
    status: str
    insight_status: str | None
    department: DepartmentShort | None
    synced_at: datetime | None


class ComputerDetail(ComputerOut):
    serial_number: str | None
    ip_address: str | None
    note: str | None
    attributes: dict[str, Any]


class TierSummary(BaseModel):
    tier: str
    available: int
    total: int
    min_ram_gb: int | None
    max_ram_gb: int | None
