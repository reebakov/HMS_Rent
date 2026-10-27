"""Очередь очистки: вернувшиеся ПК, которые исполнитель ещё не очистил (статус `cleaning`).

Вынесена отдельно от executor и overdue, чтобы обоим не импортировать друг друга.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, BookingStatus, Computer, ComputerStatus

LIMIT = 200


async def list_waiting(session: AsyncSession, *, older_than: timedelta | None = None) -> list[Booking]:
    """Последняя возвращённая бронь каждого ПК на очистке, давние первыми; `older_than` — только ждущие дольше срока."""
    stmt = (
        select(Booking).join(Computer, Computer.id == Booking.computer_id)
        .where(Computer.status == ComputerStatus.cleaning, Booking.status == BookingStatus.returned,
               Booking.returned_at.is_not(None))
        .order_by(Booking.returned_at.desc(), Booking.id.desc())
    )
    latest: dict[int, Booking] = {}
    for booking in (await session.scalars(stmt)).unique():
        latest.setdefault(booking.computer_id, booking)  # у ПК могло быть несколько возвратов: берём последний
    rows = sorted(latest.values(), key=lambda b: (b.returned_at, b.id))
    if older_than is not None:
        border = datetime.now(timezone.utc) - older_than
        rows = [b for b in rows if b.returned_at and b.returned_at < border]
    return rows[:LIMIT]
