from app.core.admins import is_admin_email
from app.integrations.auth.base import AuthError, AuthResult


def dev_login(username: str) -> AuthResult:
    """Только для локальной разработки (AUTH_DEV_ENABLED=true): любой логин, пароль не нужен.

    Логин «admin» или адрес из config/admins.txt получает роль администратора.
    """
    username = username.strip().lower()
    if not username:
        raise AuthError("Введите логин")
    return AuthResult(
        username=username,
        display_name=username.split("@")[0].capitalize(),
        email=username if "@" in username else None,
        is_admin=username == "admin" or is_admin_email(username),
    )
