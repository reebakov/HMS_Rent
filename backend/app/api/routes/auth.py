import time
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import settings
from app.core.security import create_oauth_state, create_session_token, read_oauth_state, verify_password
from app.integrations.auth import google
from app.integrations.auth.base import AuthError, AuthResult
from app.integrations.auth.dev import dev_login
from app.models import User, UserRole
from app.schemas.auth import AuthConfigOut, LoginIn, SessionOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_COOKIE = "hmsrent_oauth"
_failed: dict[str, list[float]] = defaultdict(list)  # логин -> время неудачных попыток (в памяти процесса)


def _session_out(user: User) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(user), app_name=settings.app_name, insight_mode=settings.insight_mode)


def _set_session(response: Response, user: User) -> None:
    response.set_cookie(
        settings.cookie_name,
        create_session_token(user.id, user.username, user.role),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def _check_throttle(username: str) -> None:
    window = settings.login_lock_minutes * 60
    attempts = [t for t in _failed[username] if time.time() - t < window]
    _failed[username] = attempts
    if len(attempts) >= settings.login_max_attempts:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Слишком много попыток. Повторите через {settings.login_lock_minutes} мин.")


async def _upsert_sso_user(session: DB, result: AuthResult, source: str) -> User:
    """Сотрудник из Google/dev: создаём при первом входе, обновляем имя и аватар."""
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
    user.role = UserRole.admin.value if result.is_admin else UserRole.user.value
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return user


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        app_name=settings.app_name,
        google_enabled=settings.google_enabled,
        google_domains=settings.google_domains,
        local_enabled=settings.auth_local_enabled,
        dev_enabled=settings.auth_dev_enabled,
    )


@router.post("/login", response_model=SessionOut)
async def login(data: LoginIn, response: Response, session: DB) -> SessionOut:
    """Локальные учётки администраторов (логин + пароль). В dev-режиме — вход любым логином."""
    username = data.username.strip().lower()
    _check_throttle(username)
    user = await session.scalar(select(User).where(User.username == username))

    if user is not None and user.auth_source == "local" and settings.auth_local_enabled:
        if not user.is_active or not verify_password(data.password, user.password_hash):
            _failed[username].append(time.time())
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
        _failed.pop(username, None)
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
    elif settings.auth_dev_enabled:
        try:
            user = await _upsert_sso_user(session, dev_login(username), "dev")
        except AuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    else:
        _failed[username].append(time.time())
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

    _set_session(response, user)
    return _session_out(user)


@router.get("/google/login")
async def google_login(next: str = "/") -> RedirectResponse:
    if not settings.google_enabled:
        raise HTTPException(404, "Вход через Google не настроен")
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/"
    state, nonce, cookie = create_oauth_state(safe_next)
    resp = RedirectResponse(google.authorization_url(state, nonce), status_code=302)
    resp.set_cookie(OAUTH_COOKIE, cookie, httponly=True, secure=settings.cookie_secure,
                    samesite="lax", max_age=600, path="/")
    return resp


@router.get("/google/callback")
async def google_callback(request: Request, session: DB, code: str = "", state: str = "",
                          error: str = "") -> RedirectResponse:
    saved = read_oauth_state(request.cookies.get(OAUTH_COOKIE))

    def fail(message: str) -> RedirectResponse:
        resp = RedirectResponse(f"/login?error={quote(message)}", status_code=302)
        resp.delete_cookie(OAUTH_COOKIE, path="/")
        return resp

    if error:
        return fail("Вход через Google отменён")
    if not saved or not code or saved.get("state") != state:
        return fail("Сессия входа устарела, попробуйте ещё раз")
    try:
        user = await _upsert_sso_user(session, await google.exchange_code(code, saved["nonce"]), "google")
    except AuthError as exc:
        return fail(str(exc))

    resp = RedirectResponse(saved.get("next") or "/", status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    _set_session(resp, user)
    return resp


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(settings.cookie_name, path="/")


@router.get("/me", response_model=SessionOut)
async def me(user: CurrentUser) -> SessionOut:
    return _session_out(user)
