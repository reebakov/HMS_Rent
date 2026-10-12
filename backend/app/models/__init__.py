"""Импорт всех моделей в одном месте — нужен Alembic и остальному коду."""
from app.models.booking import Booking
from app.models.computer import Computer
from app.models.department import Department
from app.models.enums import BookingStatus, ComputerStatus, EventType, Tier, UserRole
from app.models.event import AssetEvent, SyncRun
from app.models.pool import Pool
from app.models.user import User

__all__ = [
    "AssetEvent",
    "Booking",
    "BookingStatus",
    "Computer",
    "ComputerStatus",
    "Department",
    "EventType",
    "Pool",
    "SyncRun",
    "Tier",
    "User",
    "UserRole",
]
