"""Админка: настройки на сайте, сотрудники и отделы, проверка vCenter."""
from fastapi import APIRouter, HTTPException

from app.api.deps import DB, AdminUser
from app.schemas.settings import SettingsOut
from app.schemas.user import UserAdminOut, UserCreate, UserUpdate
from app.services import runtime, users, vms

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------- Настройки ----------

@router.get("/settings", response_model=SettingsOut)
async def get_settings(_: AdminUser, session: DB) -> SettingsOut:
    return runtime.settings_out(await runtime.load(session, max_age=0))


@router.patch("/settings", response_model=SettingsOut)
async def patch_settings(data: dict, _: AdminUser, session: DB) -> SettingsOut:
    try:
        cfg = await runtime.update(session, data)
    except ValueError as exc:
        raise HTTPException(422, f"Некорректное значение: {exc}") from exc
    return runtime.settings_out(cfg)


@router.post("/vsphere/check")
async def vsphere_check(_: AdminUser) -> dict:
    return await vms.check_vcenter()


# ---------- Сотрудники ----------

@router.get("/users", response_model=list[UserAdminOut])
async def list_users(_: AdminUser, session: DB) -> list[UserAdminOut]:
    return await users.list_users(session)


@router.post("/users", response_model=UserAdminOut, status_code=201)
async def add_user(data: UserCreate, _: AdminUser, session: DB) -> UserAdminOut:
    """Заранее завести сотрудника с отделом: при первом входе через Bouncer он сразу его получит."""
    return await users.add_user(session, data)


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(user_id: int, data: UserUpdate, admin: AdminUser, session: DB) -> UserAdminOut:
    return await users.update_user(session, admin, user_id, data)
