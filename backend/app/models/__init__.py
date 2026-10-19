"""Импорт всех моделей в одном месте — нужен Alembic и остальному коду."""
from app.models.booking import Booking, BookingExtension
from app.models.computer import Computer
from app.models.department import Department
from app.models.enums import (
    BookingStatus, ComputerStatus, EventType, ServiceRequestKind, SyncRunStatus, Tier, UserRole, VmStatus,
)
from app.models.event import AssetEvent, SyncRun
from app.models.pool import Pool, pool_departments
from app.models.service_request import ServiceRequest
from app.models.user import User
from app.models.vm import AppSetting, VirtualMachine

__all__ = [
    "AppSetting",
    "AssetEvent",
    "Booking",
    "BookingExtension",
    "BookingStatus",
    "Computer",
    "ComputerStatus",
    "Department",
    "EventType",
    "Pool",
    "ServiceRequest",
    "ServiceRequestKind",
    "SyncRun",
    "SyncRunStatus",
    "Tier",
    "User",
    "UserRole",
    "VirtualMachine",
    "VmStatus",
    "pool_departments",
]
