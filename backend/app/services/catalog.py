"""Каталог для сотрудников: ПК из опубликованных пулов, видимых этому сотруднику."""
import re
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFound
from app.db.search import ilike_any
from app.models import Computer, ComputerStatus, Tier, User
from app.schemas.computer import ComputerDetail, TierSummary
from app.services.pools import pool_visible, visible_pool_ids

Sort = Literal["name", "ram_desc", "ram_asc"]
GpuKind = Literal["discrete", "integrated"]

AVAILABLE = Computer.status == ComputerStatus.available

# В каталоге только ПК с описанным железом (процессор, ОЗУ, диск; видеокарта необязательна) и не слабее порога
# (по умолчанию 8 ГБ): «слабые» начинаются с 8 ГБ ОЗУ. Без описания заказчику нечего выбирать. Виртуалки не трогаем.
# Админ видит все ПК в «Инвентаризации».
HARDWARE_SHOWN = or_(
    Computer.is_virtual.is_(True),
    and_(
        Computer.ram_gb >= settings.tier_weak_min_ram_gb,
        Computer.cpu.is_not(None), Computer.cpu != "",
        Computer.storage.is_not(None), Computer.storage != "",
    ),
)


def natural_key(name: str) -> list:
    """A9 < A10 < A150 — сортировка «как у людей», а не как у строк."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _visible(user: User):
    return (Computer.is_archived.is_(False), Computer.pool_id.in_(visible_pool_ids(user)), HARDWARE_SHOWN)


async def tier_summary(session: AsyncSession, user: User) -> list[TierSummary]:
    rows = await session.execute(
        select(
            Computer.tier,
            func.count(Computer.id).filter(AVAILABLE),
            func.count(Computer.id),
            func.min(Computer.ram_gb).filter(AVAILABLE),
            func.max(Computer.ram_gb).filter(AVAILABLE),
        )
        .where(*_visible(user))
        .group_by(Computer.tier)
    )
    data = {tier: (available, total, lo, hi) for tier, available, total, lo, hi in rows.all()}
    result = []
    for tier in Tier:
        available, total, lo, hi = data.get(tier.value, (0, 0, None, None))
        result.append(TierSummary(tier=tier.value, available=available, total=total, min_ram_gb=lo, max_ram_gb=hi))
    return result


def _integrated_gpu():
    """Встроенная видеокарта: поле пусто (дискретной нет) или совпадает с шаблоном INTEGRATED_GPU. Остальное — дискретная."""
    gpu = func.coalesce(Computer.gpu, "")
    return or_(func.trim(gpu) == "", *(gpu.icontains(p, autoescape=True) for p in settings.integrated_gpu_patterns))


async def list_computers(
    session: AsyncSession,
    user: User,
    *,
    tier: Tier | None = None,
    q: str | None = None,
    min_ram: int | None = None,
    gpu: GpuKind | None = None,
    only_available: bool = True,
    sort: Sort = "name",
) -> list[Computer]:
    stmt = select(Computer).where(*_visible(user))
    if only_available:
        stmt = stmt.where(AVAILABLE)
    if tier:
        stmt = stmt.where(Computer.tier == tier.value)
    if min_ram:
        stmt = stmt.where(Computer.ram_gb >= min_ram)
    if gpu:
        stmt = stmt.where(_integrated_gpu() if gpu == "integrated" else ~_integrated_gpu())
    if q:
        stmt = stmt.where(ilike_any(q, Computer.name, Computer.hostname, Computer.cpu, Computer.gpu, Computer.location))
    computers = list((await session.scalars(stmt)).unique().all())
    if sort == "name":
        computers.sort(key=lambda c: natural_key(c.name))
    else:
        computers.sort(key=lambda c: (c.ram_gb or 0, natural_key(c.name)), reverse=sort == "ram_desc")
    return computers


async def get_computer(session: AsyncSession, user: User, computer_id: int) -> ComputerDetail:
    comp = await session.get(Computer, computer_id)
    if comp is None or comp.is_archived or not pool_visible(comp.pool, user):
        raise NotFound("Компьютер не найден")
    detail = ComputerDetail.model_validate(comp)
    if not user.is_admin:
        # «Все атрибуты Insight» — только для администраторов: обычному сотруднику не отдаём их и через API
        detail.attributes = {}
    return detail
