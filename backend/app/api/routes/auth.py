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
from app.integrations.auth import bouncer
from app.integrations.auth.base import AuthError, AuthResult
from app.integrations.auth.dev import dev_login
from app.models import User, UserRole
from app.schemas.auth import AuthConfigOut, LoginIn, SessionOut, UserOut
from app.services import runtime

router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_COOKIE = "hmsrent_oauth"
# Неудачные попытки входа живут в памяти процесса (backend запускается одним процессом).
# Основной счётчик — по паре (логин, адрес): чужой перебор не блокирует настоящему админу вход с его адреса.
# Запасной — по одному логину со всех адресов, с потолком в LOGIN_USER_LIMIT_FACTOR раз выше: если адрес
# подделан (X-Forwarded-For), перебор всё равно упирается в этот потолок.
_failed: dict[tuple[str, str], list[float]] = defaultdict(list)
_failed_by_user: dict[str, list[float]] = defaultdict(list)
LOGIN_USER_LIMIT_FACTOR = 10
_PRUNE_ABOVE = 10_000  # ключей в словаре, после которых вычищаем устаревшие (чтобы память не росла от случайных логинов)


def _session_out(user: User) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(user), app_name=settings.app_name,
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


def _recent(store: dict, key, window: float) -> list[float]:
    """Свежие попытки по ключу; устаревшие выбрасываются, пустой ключ удаляется."""
    attempts = [t for t in store.get(key, ()) if time.time() - t < window]
    if attempts:
        store[key] = attempts
    else:
        store.pop(key, None)
    return attempts


def _check_throttle(username: str, ip: str) -> None:
    window = settings.login_lock_minutes * 60
    by_pair = len(_recent(_failed, (username, ip), window))
    by_user = len(_recent(_failed_by_user, username, window))
    if by_pair >= settings.login_max_attempts or by_user >= settings.login_max_attempts * LOGIN_USER_LIMIT_FACTOR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Слишком много попыток. Повторите через {settings.login_lock_minutes} мин.")


def _register_failure(username: str, ip: str) -> None:
    now = time.time()
    _failed[(username, ip)].append(now)
    _failed_by_user[username].append(now)
    if len(_failed) > _PRUNE_ABOVE or len(_failed_by_user) > _PRUNE_ABOVE:
        window = settings.login_lock_minutes * 60
        for key in list(_failed):
            _recent(_failed, key, window)
        for key in list(_failed_by_user):
            _recent(_failed_by_user, key, window)


async def _upsert_sso_user(session: DB, result: AuthResult, source: str) -> User:
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
    user.role = UserRole.admin.value if result.is_admin else UserRole.user.value
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    return user


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
    username = data.username.strip().lower()
    ip = _client_ip(request)
    _check_throttle(username, ip)
    user = await session.scalar(select(User).where(User.username == username))

    if user is not None and user.auth_source == "local" and settings.auth_local_enabled:
        if not user.is_active or not verify_password(data.password, user.password_hash):
            _register_failure(username, ip)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
        _failed.pop((username, ip), None)
        user.last_login_at = datetime.now(timezone.utc)
        await session.commit()
    elif settings.auth_dev_enabled:
        try:
            user = await _upsert_sso_user(session, dev_login(username), "dev")
        except AuthError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    else:
        _register_failure(username, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

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
        user = await _upsert_sso_user(session, await bouncer.exchange_code(code, saved["nonce"]), "bouncer")
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
