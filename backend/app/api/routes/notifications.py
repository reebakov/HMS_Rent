from fastapi import APIRouter, status

from app.api.deps import DB, CurrentUser
from app.schemas.notification import NotificationList, NotificationOut
from app.services import notifications as service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def my_notifications(user: CurrentUser, session: DB) -> NotificationList:
    rows, unread = await service.list_for(session, user)
    return NotificationList(items=[NotificationOut.model_validate(r) for r in rows], unread=unread)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all(user: CurrentUser, session: DB) -> None:
    await service.mark_all_read(session, user)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_one(notification_id: int, user: CurrentUser, session: DB) -> None:
    await service.mark_read(session, user, notification_id)
