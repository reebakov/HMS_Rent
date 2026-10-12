"""Вход через Google (OpenID Connect, authorization code flow).

Настройка в Google Cloud — docs/GOOGLE_SSO.md. Пускаем только подтверждённые адреса
из доменов GOOGLE_ALLOWED_DOMAINS (рабочие аккаунты Google Workspace).
"""
import time
from urllib.parse import urlencode

import httpx
import jwt

from app.core.admins import is_admin_email
from app.core.config import settings
from app.integrations.auth.base import AuthError, AuthResult

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def redirect_uri() -> str:
    return settings.public_url.rstrip("/") + settings.api_prefix + "/auth/google/callback"


def authorization_url(state: str, nonce: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "prompt": "select_account",
    }
    if len(settings.google_domains) == 1:
        params["hd"] = settings.google_domains[0]  # Google сразу предложит только рабочие аккаунты
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, nonce: str) -> AuthResult:
    async with httpx.AsyncClient(timeout=10) as http:
        resp = await http.post(TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        })
    if resp.status_code != 200:
        raise AuthError("Google не подтвердил вход, попробуйте ещё раз")

    # id_token получен напрямую от Google по TLS (back-channel), поэтому по OIDC Core 3.1.3.7
    # подпись можно не проверять — проверяем издателя, аудиторию, срок и nonce.
    claims = jwt.decode(resp.json()["id_token"], options={"verify_signature": False})
    if claims.get("iss") not in ISSUERS or claims.get("aud") != settings.google_client_id:
        raise AuthError("Некорректный ответ Google")
    if claims.get("exp", 0) < time.time() or claims.get("nonce") != nonce:
        raise AuthError("Сессия входа устарела, попробуйте ещё раз")

    email = (claims.get("email") or "").lower()
    if not email or not claims.get("email_verified"):
        raise AuthError("У Google-аккаунта нет подтверждённой почты")
    domain = email.rsplit("@", 1)[-1]
    if settings.google_domains and domain not in settings.google_domains and claims.get("hd") not in settings.google_domains:
        raise AuthError(f"Вход разрешён только с рабочей почты ({', '.join(settings.google_domains)})")

    return AuthResult(
        username=email,
        display_name=claims.get("name") or email,
        email=email,
        avatar_url=claims.get("picture"),
        is_admin=is_admin_email(email),
    )
