"""Сотрудники портала: список, предварительное заведение, отдел и блокировка."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admins import is_admin_email, is_executor_email
from app.core.errors import Conflict, NotFound
from app.models import Department, User, UserRole
from app.schemas.user import UserAdminOut, UserCreate, UserUpdate
from app.services import departments


def sso_role(email: str | None, *, admin: bool = False, department: Department | None = None) -> str:
    """Роль сотрудника по спискам в config и отделу: администратор важнее исполнителя, исполнитель — тот, чья почта
    в executors.txt или кто состоит в отделе исполнителей."""
    if admin or is_admin_email(email):
        return UserRole.admin.value
    if is_executor_email(email) or (department is not None and department.is_executors):
        return UserRole.executor.value
    return UserRole.user.value


def _out(user: User) -> UserAdminOut:
    row = UserAdminOut.model_validate(user)
    row.role = sso_role(user.email, admin=user.auth_source == "local" and user.is_admin, department=user.department)
    return row


async def list_users(session: AsyncSession) -> list[UserAdminOut]:
    users = (await session.scalars(select(User).order_by(User.display_name))).unique().all()
    return [_out(u) for u in users]


async def add_user(session: AsyncSession, data: UserCreate) -> UserAdminOut:
    email = data.email.lower()
    if await session.scalar(select(User).where(User.username == email)):
        raise Conflict("Такой сотрудник уже есть")
    if data.department_id is not None:
        await departments.get(session, data.department_id)
    user = User(username=email, email=email, display_name=data.display_name or email.split("@")[0],
                auth_source="microsoft", department_id=data.department_id)
    session.add(user)
    await session.commit()
    return _out(await session.get(User, user.id, populate_existing=True))


async def update_user(session: AsyncSession, admin: User, user_id: int, data: UserUpdate) -> UserAdminOut:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFound("Сотрудник не найден")
    changes = data.model_dump(exclude_unset=True)
    if "department_id" in changes:
        if changes["department_id"] is not None:
            await departments.get(session, changes["department_id"])
        user.department_id = changes["department_id"]
    if "is_active" in changes:
        if user.id == admin.id and not changes["is_active"]:
            raise Conflict("Нельзя заблокировать самого себя")
        user.is_active = bool(changes["is_active"])
    await session.commit()
    return _out(await session.get(User, user.id, populate_existing=True))
