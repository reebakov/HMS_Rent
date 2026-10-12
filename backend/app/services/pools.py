"""Пулы выдачи: какие компьютеры видны сотрудникам в каталоге."""
import re

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, NotFound
from app.models import Computer, ComputerStatus, EventType, Pool, User
from app.services.events import add_event


def published_pool_ids():
    """Подзапрос: id опубликованных пулов — только их ПК попадают в каталог."""
    return select(Pool.id).where(Pool.is_published.is_(True))


async def pool_stats(session: AsyncSession) -> list[dict]:
    pools = (await session.scalars(select(Pool).order_by(Pool.name))).all()
    rows = await session.execute(
        select(
            Computer.pool_id,
            func.count(Computer.id),
            func.count(Computer.id).filter(Computer.status == ComputerStatus.available),
            func.count(Computer.id).filter(Computer.status == ComputerStatus.booked),
        )
        .where(Computer.pool_id.is_not(None), Computer.is_archived.is_(False))
        .group_by(Computer.pool_id)
    )
    counts = {pool_id: (total, free, booked) for pool_id, total, free, booked in rows.all()}
    return [
        {"pool": p, "total": counts.get(p.id, (0, 0, 0))[0], "available": counts.get(p.id, (0, 0, 0))[1],
         "booked": counts.get(p.id, (0, 0, 0))[2]}
        for p in pools
    ]


def parse_names(text: str) -> list[str]:
    """«A24, A432\nA434 a442» -> ["a24", "a432", "a434", "a442"]"""
    return list(dict.fromkeys(n.lower() for n in re.split(r"[\s,;]+", text) if n))


async def assign(
    session: AsyncSession,
    admin: User,
    pool_id: int | None,
    *,
    computer_ids: list[int] | None = None,
    names: str | None = None,
) -> dict:
    """Положить ПК в пул (pool_id=None — убрать из пулов). Можно по id или списком имён/ключей Insight."""
    pool = None
    if pool_id is not None:
        pool = await session.get(Pool, pool_id)
        if pool is None:
            raise NotFound("Пул не найден")

    stmt = select(Computer).where(Computer.is_archived.is_(False))
    wanted = parse_names(names or "")
    if computer_ids:
        stmt = stmt.where(Computer.id.in_(computer_ids))
    elif wanted:
        stmt = stmt.where(func.lower(Computer.name).in_(wanted) | func.lower(Computer.insight_key).in_(wanted))
    else:
        return {"updated": 0, "not_found": []}

    computers = (await session.scalars(stmt)).unique().all()
    found = {c.name.lower() for c in computers} | {(c.insight_key or "").lower() for c in computers}
    updated = 0
    for comp in computers:
        if comp.pool_id == pool_id:
            continue
        old = comp.pool.name if comp.pool else None
        comp.pool_id = pool_id
        updated += 1
        add_event(
            session, computer_id=comp.id, actor_id=admin.id, event_type=EventType.admin_update,
            message=f"Пул: {old or '—'} → {pool.name if pool else '—'}",
        )
    await session.commit()
    return {"updated": updated, "not_found": [n for n in wanted if n not in found]}


async def delete_pool(session: AsyncSession, pool_id: int) -> None:
    pool = await session.get(Pool, pool_id)
    if pool is None:
        raise NotFound("Пул не найден")
    booked = await session.scalar(
        select(func.count(Computer.id)).where(Computer.pool_id == pool_id, Computer.status == ComputerStatus.booked)
    )
    if booked:
        raise Conflict(f"В пуле {booked} забронированных ПК — сначала дождитесь возврата или перенесите их")
    await session.execute(update(Computer).where(Computer.pool_id == pool_id).values(pool_id=None))
    await session.delete(pool)
    await session.commit()
