"""Админка: настройки на сайте, сотрудники и отделы, проверка vCenter."""
import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.api.deps import DB, AdminUser
from app.core.admins import is_admin_email
from app.core.config import settings
from app.integrations.vsphere import client as vsphere
from app.models import Department, User
from app.schemas.common import DepartmentShort, ORMModel, reject_explicit_null
from app.services import runtime
from app.services.runtime import RuntimeConfig

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Настройки ----------

class SettingsOut(RuntimeConfig):
    vsphere_configured: bool
    vcenter_host: str


@router.get("/settings", response_model=SettingsOut)
async def get_settings(_: AdminUser, session: DB) -> SettingsOut:
    cfg = await runtime.load(session, max_age=0)
    return SettingsOut(**cfg.model_dump(), vsphere_configured=settings.vsphere_configured,
                       vcenter_host=settings.vcenter_host)


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(data: dict, _: AdminUser, session: DB) -> SettingsOut:
    allowed = set(RuntimeConfig.model_fields)
    changes = {k: v for k, v in data.items() if k in allowed}
    try:
        cfg = await runtime.update(session, changes)
    except ValueError as exc:
        raise HTTPException(422, f"Некорректное значение: {exc}") from exc
    return SettingsOut(**cfg.model_dump(), vsphere_configured=settings.vsphere_configured,
                       vcenter_host=settings.vcenter_host)


@router.post("/vsphere/check")
async def vsphere_check(_: AdminUser) -> dict:
    try:
        names = [t.template for t in runtime.current().vm_templates if t.enabled and t.template]
        return {"ok": True, **(await asyncio.to_thread(vsphere.check, names))}
    except vsphere.VSphereError as exc:
        return {"ok": False, "error": str(exc)}


# ---------- Сотрудники ----------

class UserAdminOut(ORMModel):
    id: int
    username: str
    display_name: str
    email: str | None
    auth_source: str
    role: str
    is_active: bool
    department: DepartmentShort | None
    last_login_at: datetime | None


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=128, pattern=r"^[^@\s]+@[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=255)
    department_id: int | None = None


class UserUpdate(BaseModel):
    department_id: int | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _no_null(self):
        reject_explicit_null(self, "is_active")
        return self


def _out(user: User) -> UserAdminOut:
    row = UserAdminOut.model_validate(user)
    row.role = "admin" if user.auth_source == "local" and user.is_admin or is_admin_email(user.email) else "user"
    return row


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(_: AdminUser, session: DB) -> list[UserAdminOut]:
    users = (await session.scalars(select(User).order_by(User.display_name))).unique().all()
    return [_out(u) for u in users]


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def add_user(data: UserCreate, _: AdminUser, session: DB) -> UserAdminOut:
    """Заранее завести сотрудника с отделом: при первом входе через Bouncer он сразу его получит."""
    email = data.email.strip().lower()
    if await session.scalar(select(User).where(User.username == email)):
        raise HTTPException(409, "Такой сотрудник уже есть")
    if data.department_id is not None and await session.get(Department, data.department_id) is None:
        raise HTTPException(404, "Отдел не найден")
    user = User(username=email, email=email, display_name=data.display_name or email.split("@")[0],
                auth_source="microsoft", department_id=data.department_id)
    session.add(user)
    await session.commit()
    return _out(await session.get(User, user.id, populate_existing=True))


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(user_id: int, data: UserUpdate, admin: AdminUser, session: DB) -> UserAdminOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Сотрудник не найден")
    changes = data.model_dump(exclude_unset=True)
    if "department_id" in changes:
        if changes["department_id"] is not None and await session.get(Department, changes["department_id"]) is None:
            raise HTTPException(404, "Отдел не найден")
        user.department_id = changes["department_id"]
    if "is_active" in changes:
        if user.id == admin.id and not changes["is_active"]:
            raise HTTPException(409, "Нельзя заблокировать самого себя")
        user.is_active = bool(changes["is_active"])
    await session.commit()
    return _out(await session.get(User, user.id, populate_existing=True))
