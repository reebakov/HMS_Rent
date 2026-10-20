"""Простой серверов: сколько ПК опубликованных пулов стоят свободными и как давно их не выдавали."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models import Booking, Computer, ComputerStatus, Pool
from app.schemas.admin import IdleServer, IdleServers


def _local_date(moment: datetime):
    return moment.astimezone(clock.display_tz()).date()


async def list_idle(session: AsyncSession) -> IdleServers:
    """Простой считается от возврата последней брони, а если ПК не выдавали, — от появления в учёте."""
    last_return = (
        select(Booking.computer_id, func.max(Booking.returned_at).label("returned"))
        .group_by(Booking.computer_id).subquery()
    )
    rows = (await session.execute(
        select(Computer.id, Computer.name, func.coalesce(last_return.c.returned, Computer.created_at))
        .join(Pool, Pool.id == Computer.pool_id)
        .outerjoin(last_return, last_return.c.computer_id == Computer.id)
        .where(Computer.status == ComputerStatus.available, Computer.is_archived.is_(False), Pool.is_published.is_(True))
    )).all()
    today = clock.today()
    servers = sorted(
        (IdleServer(id=cid, name=name, idle_since=(since := _local_date(moment)), idle_days=max((today - since).days, 0))
         for cid, name, moment in rows),
        key=lambda s: (-s.idle_days, s.name),
    )
    average = round(sum(s.idle_days for s in servers) / len(servers)) if servers else 0
    return IdleServers(count=len(servers), average_days=average, items=servers)
