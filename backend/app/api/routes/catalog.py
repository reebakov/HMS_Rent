import re
from typing import Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.models import Computer, ComputerStatus, Department, Tier
from app.schemas.computer import ComputerDetail, ComputerOut, TierSummary
from app.schemas.department import DepartmentOut
from app.services.pools import pool_visible, visible_pool_ids

router = APIRouter(tags=["catalog"])

AVAILABLE = Computer.status == ComputerStatus.available


def natural_key(name: str) -> list:
    """A9 < A10 < A150 — сортировка «как у людей», а не как у строк."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


@router.get("/catalog/summary", response_model=list[TierSummary])
async def catalog_summary(user: CurrentUser, session: DB) -> list[TierSummary]:
    rows = await session.execute(
        select(
            Computer.tier,
            func.count(Computer.id).filter(AVAILABLE),
            func.count(Computer.id),
            func.min(Computer.ram_gb).filter(AVAILABLE),
            func.max(Computer.ram_gb).filter(AVAILABLE),
        )
        .where(Computer.is_archived.is_(False), Computer.pool_id.in_(visible_pool_ids(user)))
        .group_by(Computer.tier)
    )
    data = {tier: (available, total, lo, hi) for tier, available, total, lo, hi in rows.all()}
    result = []
    for tier in Tier:
        available, total, lo, hi = data.get(tier.value, (0, 0, None, None))
        result.append(TierSummary(tier=tier.value, available=available, total=total, min_ram_gb=lo, max_ram_gb=hi))
    return result


@router.get("/computers", response_model=list[ComputerOut])
async def list_computers(
    user: CurrentUser,
    session: DB,
    tier: Tier | None = None,
    q: str | None = None,
    min_ram: int | None = None,
    gpu_only: bool = False,
    only_available: bool = True,
    sort: Literal["name", "ram_desc", "ram_asc"] = "name",
) -> list[Computer]:
    stmt = select(Computer).where(Computer.is_archived.is_(False), Computer.pool_id.in_(visible_pool_ids(user)))
    if only_available:
        stmt = stmt.where(AVAILABLE)
    if tier:
        stmt = stmt.where(Computer.tier == tier.value)
    if min_ram:
        stmt = stmt.where(Computer.ram_gb >= min_ram)
    if gpu_only:
        stmt = stmt.where(Computer.gpu.is_not(None), Computer.gpu != "")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(
            Computer.name.ilike(like), Computer.hostname.ilike(like), Computer.cpu.ilike(like),
            Computer.gpu.ilike(like), Computer.location.ilike(like),
        ))
    computers = list((await session.scalars(stmt)).unique().all())
    if sort == "name":
        computers.sort(key=lambda c: natural_key(c.name))
    else:
        computers.sort(key=lambda c: (c.ram_gb or 0, natural_key(c.name)), reverse=sort == "ram_desc")
    return computers


@router.get("/computers/{computer_id}", response_model=ComputerDetail)
async def get_computer(computer_id: int, user: CurrentUser, session: DB) -> Computer:
    comp = await session.get(Computer, computer_id)
    hidden = comp is not None and not pool_visible(comp.pool, user)
    if comp is None or comp.is_archived or hidden:
        raise HTTPException(404, "Компьютер не найден")
    return comp


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(_: CurrentUser, session: DB) -> list[Department]:
    rows = await session.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.name))
    return list(rows.all())
