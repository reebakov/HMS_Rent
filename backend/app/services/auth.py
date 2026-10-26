"""Вход: локальные учётки, dev-вход и заведение SSO-сотрудников."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import verify_password
from app.integrations.auth.base import AuthError, AuthResult
from app.integrations.auth.dev import dev_login
from app.models import User
from app.services import auth_throttle
from app.services.users import sso_role

BAD_CREDENTIALS = "Неверный логин или пароль"


async def upsert_sso_user(session: AsyncSession, result: AuthResult, source: str) -> User:
    """Сотрудник из Bouncer/dev: создаём при первом входе, обновляем имя."""
    user = await session.scalar(select(User).where(User.username == result.username))
    if user is None:
        user = User(username=result.username, auth_source=source)
        session.add(user)
    elif not user.is_active:
        raise AuthError("Учётная запись отключена администратором портала")
    elif user.auth_source == "local":
        raise AuthError("Этот логин принадлежит локальной учётке администратора")
    user.display_name = result.display_name
    user.email = result.email
    user.avatar_url = result.avatar_url
    user.role = sso_role(result.email or result.username, admin=result.is_admin, department=user.department)
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return user


async def login(session: AsyncSession, username: str, password: str, ip: str) -> User:
    """Локальные учётки администраторов (логин + пароль). В dev-режиме — вход любым логином."""
    username = username.strip().lower()
    auth_throttle.check(username, ip)
    user = await session.scalar(select(User).where(User.username == username))

    if user is not None and user.auth_source == "local" and settings.auth_local_enabled:
        # scrypt занимает десятки миллисекунд процессора: в потоке, чтобы не стопорить event loop
        if not user.is_active or not await asyncio.to_thread(verify_password, password, user.password_hash):
            auth_throttle.register_failure(username, ip)
            raise Unauthorized(BAD_CREDENTIALS)
        auth_throttle.reset(username, ip)
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
        return user
    if settings.auth_dev_enabled:
        try:
            return await upsert_sso_user(session, dev_login(username), "dev")
        except AuthError as exc:
            raise Unauthorized(str(exc)) from exc
    auth_throttle.register_failure(username, ip)
    raise Unauthorized(BAD_CREDENTIALS)
