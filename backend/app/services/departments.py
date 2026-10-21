"""Справочник отделов."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.db.integrity import conflict_on_integrity_error
from app.models import Department, User
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


async def for_order(session: AsyncSession, user: User, requested: int | None) -> Department:
    """Отдел заказа (команда, которой доступен заказ): отдел сотрудника.

    Обычный сотрудник оформляет заказ только на свой отдел: без отдела заказ нельзя оформить (его назначает админ),
    чужой отдел — отказ. Админ может оформить на любой активный отдел, а если не указал — на свой.
    """
    if user.is_admin:
        dept_id = requested or user.department_id
        if dept_id is None:
            raise DomainError("Укажите отдел заказа")
        return await get_active(session, dept_id)
    if user.department_id is None:
        raise Conflict("Вам не назначен отдел. Обратитесь к администратору")
    if requested not in (None, user.department_id):
        raise Forbidden("Заказ оформляется на ваш отдел")
    dept = await session.get(Department, user.department_id)
    if dept is None or not dept.is_active:
        raise Conflict("Ваш отдел отключён. Обратитесь к администратору")
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
