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

VIEW_AS_COOKIE = "hmsrent_view_as"  # режим «Открыть как пользователь» (только просмотр, см. get_current_user)
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _apply_role(user: User) -> User:
    if user.auth_source != "local":
        # права SSO-пользователей (Bouncer) берутся из config/admins.txt и config/executors.txt на каждом запросе:
        # добавили/убрали почту — изменение действует сразу, без повторного входа
        # dev/admin — админ только пока включён AUTH_DEV_ENABLED: демо-запись, попавшая на прод, прав не даёт
        dev_admin = settings.auth_dev_enabled and user.auth_source == "dev" and user.username == "admin"
        user.role = sso_role(user.email or user.username, admin=dev_admin)
    return user


async def get_real_user(request: Request, session: DB) -> User:
    """Тот, кто вошёл в портал (по сессионной cookie), даже если включён режим просмотра чужими глазами."""
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
    return _apply_role(user)


async def get_current_user(request: Request, session: DB) -> User:
    """Пользователь, чьими глазами смотрит портал. Обычно это вошедший, а у администратора в режиме просмотра —
    выбранный сотрудник: с его правами и данными, но только на чтение (любой запрос, кроме GET, отклоняется)."""
    real = await get_real_user(request, session)
    request.state.real_user = real
    token = request.cookies.get(VIEW_AS_COOKIE)
    payload = decode_session_token(token) if token and real.is_admin else None
    if not payload or payload.get("adm") != real.id:  # cookie другого администратора или уже не администратор — игнорируем
        return real
    target = await session.get(User, int(payload["sub"])) if str(payload.get("sub", "")).isdigit() else None
    if target is None or not target.is_active or target.id == real.id:
        return real
    if request.method not in SAFE_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Режим просмотра: действия недоступны, выйдите из него, чтобы работать")
    return _apply_role(target)


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
