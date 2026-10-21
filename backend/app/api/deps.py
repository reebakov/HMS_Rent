from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_session_token
from app.db.session import get_session
from app.models import User
from app.services import runtime
from app.services.users import sso_role

DB = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, session: DB) -> User:
    token = request.cookies.get(settings.cookie_name)
    payload = decode_session_token(token) if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):  # подпись верна, но токен без sub или с мусором в sub
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход") from None
    await runtime.load(session)  # свежие настройки с сайта (кэш 5 с)
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или отключён")
    if user.auth_source != "local":
        # права SSO-пользователей (Bouncer) берутся из config/admins.txt и config/executors.txt на каждом запросе:
        # добавили/убрали почту — изменение действует сразу, без повторного входа
        # dev/admin — админ только пока включён AUTH_DEV_ENABLED: демо-запись, попавшая на прод, прав не даёт
        dev_admin = settings.auth_dev_enabled and user.auth_source == "dev" and user.username == "admin"
        user.role = sso_role(user.email or user.username, admin=dev_admin)
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора")
    return user


async def require_executor(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_executor:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права исполнителя")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
ExecutorUser = Annotated[User, Depends(require_executor)]
