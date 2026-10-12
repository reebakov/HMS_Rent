from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admins import is_admin_email
from app.core.config import settings
from app.core.security import decode_session_token
from app.db.session import get_session
from app.models import User, UserRole

DB = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, session: DB) -> User:
    token = request.cookies.get(settings.cookie_name)
    payload = decode_session_token(token) if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    user = await session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или отключён")
    if user.auth_source != "local":
        # права Google-пользователей берутся из config/admins.txt на каждом запросе:
        # добавили/убрали почту — изменение действует сразу, без повторного входа
        admin = is_admin_email(user.email or user.username) or (user.auth_source == "dev" and user.username == "admin")
        user.role = UserRole.admin.value if admin else UserRole.user.value
    return user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
