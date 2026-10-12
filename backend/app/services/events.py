from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AssetEvent


def add_event(
    session: AsyncSession,
    *,
    computer_id: int,
    event_type: str,
    message: str = "",
    actor_id: int | None = None,
    booking_id: int | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AssetEvent:
    event = AssetEvent(
        computer_id=computer_id,
        event_type=event_type,
        message=message,
        actor_id=actor_id,
        booking_id=booking_id,
        from_status=from_status,
        to_status=to_status,
        payload=payload or {},
    )
    session.add(event)
    return event
