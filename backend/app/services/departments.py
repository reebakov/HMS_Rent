"""Справочник отделов."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.db.integrity import conflict_on_integrity_error
from app.models import Department
from app.schemas.department import DepartmentCreate, DepartmentUpdate

NAME_TAKEN = "Отдел с таким названием уже есть"


async def list_active(session: AsyncSession) -> list[Department]:
    rows = await session.scalars(select(Department).where(Department.is_active.is_(True)).order_by(Department.name))
    return list(rows.all())


async def get(session: AsyncSession, department_id: int) -> Department:
    dept = await session.get(Department, department_id)
    if dept is None:
        raise NotFound("Отдел не найден")
    return dept


async def get_active(session: AsyncSession, department_id: int) -> Department:
    """Отдел, на который можно оформлять аренду: отключённый считается ненайденным."""
    dept = await session.get(Department, department_id)
    if dept is None or not dept.is_active:
        raise NotFound("Отдел не найден")
    return dept


async def get_many(session: AsyncSession, ids: list[int]) -> list[Department]:
    if not ids:
        return []
    found = list((await session.scalars(select(Department).where(Department.id.in_(ids)))).all())
    if len(found) != len(set(ids)):
        raise NotFound("Один из отделов не найден")
    return found


async def create(session: AsyncSession, data: DepartmentCreate) -> Department:
    dept = Department(name=data.name, code=data.code, head_name=data.head_name)
    session.add(dept)
    async with conflict_on_integrity_error(session, NAME_TAKEN):
        await session.commit()
    return dept


async def update(session: AsyncSession, department_id: int, data: DepartmentUpdate) -> Department:
    dept = await get(session, department_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(dept, field, value)
    async with conflict_on_integrity_error(session, NAME_TAKEN):
        await session.commit()
    return dept
