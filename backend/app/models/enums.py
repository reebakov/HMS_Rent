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
    cleaning = "cleaning"        # вернули, ждёт очистки диска исполнителем (портал держит статус до подтверждения)
    maintenance = "maintenance"  # ремонт / обслуживание
    retired = "retired"          # списан
    unknown = "unknown"          # статус Insight не распознан


class BookingStatus(StrEnum):
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class VmStatus(StrEnum):
    """Жизненный цикл ВМ: queued → creating → ready → deleting → deleted; при ошибке — failed."""

    queued = "queued"
    creating = "creating"
    ready = "ready"
    deleting = "deleting"
    deleted = "deleted"
    failed = "failed"


class TermRequestStatus(StrEnum):
    pending = "pending"    # ждёт решения администратора
    approved = "approved"
    rejected = "rejected"


class SyncRunStatus(StrEnum):
    running = "running"
    success = "success"
    failed = "failed"


class ServiceRequestKind(StrEnum):
    problem = "problem"  # «Сообщить о проблеме» из «Моей аренды»
    return_ = "return"   # заявка на возврат ПК (return — зарезервированное слово)
    prepare = "prepare"  # подготовить ПК после брони: поставить выбранную ОС
    build = "build"      # сборка по запросу из каталога (без ПК и ВМ, привязана к команде)
    diagnose = "diagnose"  # «Диагностика комплекта»: исполнитель отметил ПК неисправным (без привязки к заказу)


class EventType(StrEnum):
    booked = "booked"
    returned = "returned"
    extended = "extended"
    prepared = "prepared"  # исполнитель подготовил ПК и внёс данные для подключения
    rejected = "rejected"  # исполнитель отклонил заказ ПК (в том числе «Сервер неисправен»)
    cleaned = "cleaned"    # исполнитель очистил диск вернувшегося ПК, ПК свободен
    insight_created = "insight_created"
    insight_status_changed = "insight_status_changed"
    insight_removed = "insight_removed"
    insight_pool_changed = "insight_pool_changed"
    admin_update = "admin_update"
    writeback_failed = "writeback_failed"


class NotificationKind(StrEnum):
    """Что случилось с заказом заказчика; по виду фронтенд выбирает значок и цвет."""

    pc_ready = "pc_ready"  # исполнитель подготовил ПК, данные для подключения в «Моей аренде»
    order_rejected = "order_rejected"  # исполнитель отклонил заказ ПК, причина в уведомлении
    vm_ready = "vm_ready"
    vm_failed = "vm_failed"
    request_status = "request_status"  # сменился статус заявки в Service Desk
    term_decision = "term_decision"    # админ согласовал или отклонил срок дольше лимита
    term_ending = "term_ending"        # срок аренды скоро закончится
    term_overdue = "term_overdue"      # срок аренды закончился


class UserRole(StrEnum):
    user = "user"
    executor = "executor"  # исполнитель HMS: готовит выданные ПК и вносит данные для подключения
    admin = "admin"
