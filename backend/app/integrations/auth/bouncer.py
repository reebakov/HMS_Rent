"""Вход через корпоративный SSO (Bouncer) по стандарту OpenID Connect."""
import time
from urllib.parse import urlencode
import httpx
import jwt

from app.core.admins import is_admin_email
from app.core.config import settings
from app.integrations.auth.base import AuthError, AuthResult

def redirect_uri() -> str:
    return settings.public_url.rstrip("/") + settings.api_prefix + "/auth/bouncer/callback"

def authorization_url(state: str, nonce: str) -> str:
    params = {
        "client_id": settings.bouncer_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    return f"{settings.bouncer_authorize_url}?{urlencode(params)}"

async def exchange_code(code: str, nonce: str) -> AuthResult:
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(settings.bouncer_token_url, data={
                "code": code,
                "client_id": settings.bouncer_client_id,
                "client_secret": settings.bouncer_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            })
    except httpx.HTTPError as exc:  # недоступен или не ответил вовремя
        raise AuthError("Сервер авторизации (Bouncer) недоступен, попробуйте позже") from exc
    if resp.status_code != 200:
        raise AuthError("Сервер авторизации (Bouncer) отклонил запрос")

    try:
        data = resp.json()
    except ValueError as exc:  # например, HTML-страница ошибки от прокси
        raise AuthError("Bouncer вернул некорректный ответ") from exc
    if not isinstance(data, dict) or "id_token" not in data:
        raise AuthError("Bouncer не вернул id_token")

    try:
        claims = jwt.decode(data["id_token"], options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise AuthError("Bouncer вернул некорректный id_token") from exc
    
    if claims.get("exp", 0) < time.time() or claims.get("nonce") != nonce:
        raise AuthError("Сессия входа устарела, попробуйте ещё раз")

    # Ищем логин в стандартных полях
    candidates = [str(claims.get(k) or "").strip().lower() for k in ("email", "preferred_username", "upn", "sub")]
    candidates = [c for c in candidates if c]
    if not candidates:
        raise AuthError("Bouncer не передал email или логин пользователя")
    
    username = candidates[0]

    return AuthResult(
        username=username,
        display_name=claims.get("name") or claims.get("given_name") or username.split("@")[0],
        email=username if "@" in username else None,
        avatar_url=None,
        is_admin=any(is_admin_email(c) for c in candidates),
    )