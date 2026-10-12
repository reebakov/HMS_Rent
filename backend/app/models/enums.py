from enum import StrEnum


class Tier(StrEnum):
    """Категория мощности — то, что пользователь выбирает на первом экране."""

    weak = "weak"
    medium = "medium"
    powerful = "powerful"
    vm = "vm"


class ComputerStatus(StrEnum):
    available = "available"      # свободен, можно бронировать
    booked = "booked"            # закреплён за отделом через портал
    in_use = "in_use"            # по Insight занят (выдан мимо портала)
    maintenance = "maintenance"  # ремонт / обслуживание
    retired = "retired"          # списан
    unknown = "unknown"          # статус Insight не распознан


class BookingStatus(StrEnum):
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class EventType(StrEnum):
    booked = "booked"
    returned = "returned"
    insight_created = "insight_created"
    insight_status_changed = "insight_status_changed"
    insight_removed = "insight_removed"
    admin_update = "admin_update"
    writeback_failed = "writeback_failed"


class UserRole(StrEnum):
    user = "user"
    admin = "admin"
