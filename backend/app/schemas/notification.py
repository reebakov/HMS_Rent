from datetime import datetime

from app.models import NotificationKind
from app.schemas.common import ORMModel


class NotificationOut(ORMModel):
    id: int
    kind: NotificationKind
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class NotificationList(ORMModel):
    items: list[NotificationOut]
    unread: int  # всего непрочитанных, а не только в items
