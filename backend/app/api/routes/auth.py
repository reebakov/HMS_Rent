import logging
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import DB, VIEW_AS_COOKIE, CurrentUser, get_real_user
from app.core.config import settings
from app.core.security import create_oauth_state, create_session_token, create_view_as_token, read_oauth_state
from app.integrations.auth import bouncer
from app.integrations.auth.base import AuthError
from app.models import User
from app.schemas.auth import AuthConfigOut, LoginIn, SessionOut, UserOut, ViewAsBy, ViewAsIn
from app.services import auth, runtime

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

OAUTH_COOKIE = "hmsrent_oauth"


def _session_out(user: User, viewer: User | None = None) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(user), view_as_by=ViewAsBy.model_validate(viewer) if viewer else None,
                      app_name=settings.app_name,
                      app_subtitle=settings.app_subtitle, insight_mode=settings.insight_mode,
                      catalog_refresh_sec=runtime.current().catalog_refresh_sec)


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


def _client_ip(request: Request) -> str:
    """Адрес клиента. За nginx это последний элемент X-Forwarded-For (его дописывает сам nginx)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    return AuthConfigOut(
        app_name=settings.app_name,
        bouncer_enabled=settings.bouncer_enabled,
        local_enabled=settings.auth_local_enabled,
        dev_enabled=settings.auth_dev_enabled,
    )


@router.post("/login", response_model=SessionOut)
async def login(data: LoginIn, request: Request, response: Response, session: DB) -> SessionOut:
    """Локальные учётки администраторов (логин + пароль). В dev-режиме — вход любым логином."""
    user = await auth.login(session, data.username, data.password, _client_ip(request))
    _set_session(response, user)
    return _session_out(user)


def _safe_next(path: str) -> str:
    """Куда вернуть после входа: только путь на этом же сайте.

    Браузеры читают «/\\evil.com» как «//evil.com», а табуляцию и перевод строки внутри URL выбрасывают
    (после «/» и табуляции получается тот же «//»), поэтому обратная косая и управляющие символы отклоняются.
    """
    if not path.startswith("/") or path.startswith("//") or "\\" in path or any(c < " " or c == "\x7f" for c in path):
        return "/"
    return path


@router.get("/bouncer/login")
async def bouncer_login(next: str = "/") -> RedirectResponse:
    if not settings.bouncer_enabled:
        raise HTTPException(404, "Вход через Bouncer не настроен")
    state, nonce, cookie = create_oauth_state(_safe_next(next))
    resp = RedirectResponse(bouncer.authorization_url(state, nonce), status_code=302)
    resp.set_cookie(OAUTH_COOKIE, cookie, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=600, path="/")
    return resp


@router.get("/bouncer/callback")
async def bouncer_callback(request: Request, session: DB, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    saved = read_oauth_state(request.cookies.get(OAUTH_COOKIE))

    def fail(message: str) -> RedirectResponse:
        resp = RedirectResponse(f"/login?error={quote(message)}", status_code=302)
        resp.delete_cookie(OAUTH_COOKIE, path="/")
        return resp

    if error:
        return fail("Вход отменён")
    if not saved or not code or saved.get("state") != state:
        return fail("Сессия входа устарела, попробуйте ещё раз")
    try:
        user = await auth.upsert_sso_user(session, await bouncer.exchange_code(code, saved["nonce"]), "bouncer")
    except AuthError as exc:
        return fail(str(exc))

    resp = RedirectResponse(saved.get("next") or "/", status_code=302)
    resp.delete_cookie(OAUTH_COOKIE, path="/")
    _set_session(resp, user)
    return resp


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(VIEW_AS_COOKIE, path="/")


@router.get("/me", response_model=SessionOut)
async def me(request: Request, user: CurrentUser) -> SessionOut:
    real = request.state.real_user
    return _session_out(user, real if real.id != user.id else None)


@router.post("/view-as", response_model=SessionOut)
async def view_as(data: ViewAsIn, response: Response, session: DB, admin: Annotated[User, Depends(get_real_user)]) -> SessionOut:
    """Администратор открывает портал глазами сотрудника: только просмотр, действия отклоняются (см. get_current_user)."""
    if not admin.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Нужны права администратора")
    target = await session.get(User, data.user_id)
    if target is None or not target.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден или отключён")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Это вы сами: режим просмотра нужен для другого сотрудника")
    response.set_cookie(
        VIEW_AS_COOKIE, create_view_as_token(admin.id, target.id), httponly=True, secure=settings.cookie_secure,
        samesite="lax", max_age=settings.session_ttl_hours * 3600, path="/",
    )
    log.info("Администратор %s открыл портал глазами %s", admin.username, target.username)
    return _session_out(target, admin)


@router.delete("/view-as", response_model=SessionOut)
async def stop_view_as(response: Response, user: Annotated[User, Depends(get_real_user)]) -> SessionOut:
    response.delete_cookie(VIEW_AS_COOKIE, path="/")
    return _session_out(user)
