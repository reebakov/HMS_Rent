"""Bouncer (OIDC): ссылка авторизации, обмен кода на токен (respx), разбор claims и сквозной вход через /auth/bouncer/*.
Базовые ветки роутов уже в test_api_auth.py — здесь реальный exchange_code и граничные случаи."""
import os
import time
from itertools import count
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import jwt
import pytest
from sqlalchemy import select

from app.api.routes import auth as auth_routes
from app.core import admins
from app.core.config import settings
from app.integrations.auth import bouncer
from app.integrations.auth.base import AuthError
from app.models import User
from app.services import auth_throttle

TOKEN_URL = "https://sso.example/token"
NONCE = "nonce-123"


@pytest.fixture(autouse=True)
def bouncer_on(monkeypatch):
    for k, v in dict(bouncer_client_id="cid", bouncer_client_secret="sec", bouncer_authorize_url="https://sso.example/authorize",
                     bouncer_token_url=TOKEN_URL, public_url="https://rent.corp.io/").items():
        monkeypatch.setattr(settings, k, v)
    auth_throttle._failed.clear()


@pytest.fixture
def admins_file(tmp_path, monkeypatch):
    path = tmp_path / "admins.txt"
    monkeypatch.setattr(admins, "_path", lambda: path)
    monkeypatch.setattr(admins, "_cache", (-1.0, frozenset()))
    tick = count(1_000_000_000, 10)

    def write(*lines: str) -> None:
        path.write_text("\n".join(lines), encoding="utf-8")
        t = next(tick)
        os.utime(path, (t, t))
    return write


def id_token(nonce: str | None = NONCE, exp: float | None = None, **claims) -> str:
    """Токен без проверки подписи — как его читает код. По умолчанию aud — наш client_id (cid)."""
    body = {"exp": time.time() + 600 if exp is None else exp, "aud": "cid", **claims}
    if nonce is not None:
        body["nonce"] = nonce
    return jwt.encode(body, "any-key", algorithm="HS256")


@pytest.fixture
def token_endpoint(respx_mock):
    """token_endpoint(json=..., status=200) — настраивает ответ token endpoint, возвращает route."""
    def _set(status: int = 200, **kw):
        return respx_mock.post(TOKEN_URL).respond(status, **kw)
    return _set


# ---------- authorization_url / redirect_uri ----------

def test_redirect_uri_strips_trailing_slash():
    assert bouncer.redirect_uri() == "https://rent.corp.io" + settings.api_prefix + "/auth/bouncer/callback"


def test_authorization_url_params():
    url = bouncer.authorization_url("st ate&", "no=nce")
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://sso.example/authorize"
    q = parse_qs(parsed.query)  # значения экранированы и разбираются обратно без потерь
    assert q == {"client_id": ["cid"], "redirect_uri": [bouncer.redirect_uri()], "response_type": ["code"],
                 "scope": ["openid profile email"], "state": ["st ate&"], "nonce": ["no=nce"]}


# ---------- exchange_code: запрос ----------

async def test_exchange_code_posts_form_with_credentials(token_endpoint):
    route = token_endpoint(json={"id_token": id_token(email="A@Corp.io")})
    await bouncer.exchange_code("the-code", NONCE)
    req = route.calls.last.request
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    assert {k: v[0] for k, v in parse_qs(req.content.decode()).items()} == {
        "code": "the-code", "client_id": "cid", "client_secret": "sec",
        "redirect_uri": bouncer.redirect_uri(), "grant_type": "authorization_code"}


# ---------- exchange_code: разбор claims ----------

async def test_exchange_code_success_maps_claims(token_endpoint):
    token_endpoint(json={"id_token": id_token(email="  Ivan.Petrov@Corp.IO ", name="Иван Петров")})
    r = await bouncer.exchange_code("c", NONCE)
    assert (r.username, r.email, r.display_name, r.avatar_url, r.is_admin) == (
        "ivan.petrov@corp.io", "ivan.petrov@corp.io", "Иван Петров", None, False)


@pytest.mark.parametrize("claims,username,email,display", [
    ({"preferred_username": "Ivan@Corp.io", "given_name": "Иван"}, "ivan@corp.io", "ivan@corp.io", "Иван"),  # email нет -> preferred_username
    ({"upn": "u@corp.io"}, "u@corp.io", "u@corp.io", "u"),                                                    # имени нет -> часть до @
    ({"sub": "SUB-42"}, "sub-42", None, "sub-42"),                                                           # только sub: не email
    ({"email": "", "preferred_username": "p@corp.io", "name": ""}, "p@corp.io", "p@corp.io", "p"),            # пустые значения пропускаются
    ({"email": "a@corp.io", "preferred_username": "b@corp.io"}, "a@corp.io", "a@corp.io", "a"),              # приоритет: email первым
])
async def test_exchange_code_username_candidates(token_endpoint, claims, username, email, display):
    token_endpoint(json={"id_token": id_token(**claims)})
    r = await bouncer.exchange_code("c", NONCE)
    assert (r.username, r.email, r.display_name) == (username, email, display)


async def test_exchange_code_admin_from_admins_file(token_endpoint, admins_file):
    admins_file("boss@corp.io")
    token_endpoint(json={"id_token": id_token(email="Boss@Corp.io")})
    assert (await bouncer.exchange_code("c", NONCE)).is_admin is True
    token_endpoint(json={"id_token": id_token(email="other@corp.io")})
    assert (await bouncer.exchange_code("c", NONCE)).is_admin is False


# ---------- exchange_code: ошибки ----------

@pytest.mark.parametrize("status", [400, 401, 403, 500, 502])
async def test_exchange_code_non_200_is_auth_error(token_endpoint, status):
    token_endpoint(status, json={"error": "invalid_grant"})
    with pytest.raises(AuthError, match="отклонил"):
        await bouncer.exchange_code("c", NONCE)


async def test_exchange_code_200_with_error_body_has_no_id_token(token_endpoint):
    token_endpoint(json={"access_token": "x"})
    with pytest.raises(AuthError, match="id_token"):
        await bouncer.exchange_code("c", NONCE)


@pytest.mark.parametrize("kw,why", [
    (dict(nonce="other"), "чужой nonce"),
    (dict(nonce=None), "нет nonce"),
    (dict(exp=time.time() - 1), "токен истёк"),
])
async def test_exchange_code_rejects_stale_or_replayed_token(token_endpoint, kw, why):
    token_endpoint(json={"id_token": id_token(email="a@corp.io", **kw)})
    with pytest.raises(AuthError, match="устарела"):
        await bouncer.exchange_code("c", NONCE)


# ---------- exchange_code: aud и iss ----------

INVALID_SESSION = "Сессия входа некорректна"


@pytest.mark.parametrize("aud", ["other-client", ["other-client", "another"], [], None, 42],
                         ids=["чужая строка", "чужой список", "пустой список", "нет aud", "не строка и не список"])
async def test_exchange_code_rejects_foreign_or_missing_audience(token_endpoint, caplog, aud):
    claims = {"aud": aud} if aud is not None else {}
    token = jwt.encode({"exp": time.time() + 600, "nonce": NONCE, "email": "a@corp.io", **claims}, "k", algorithm="HS256")
    token_endpoint(json={"id_token": token})
    with caplog.at_level("WARNING", logger="hmsrent.bouncer"):
        with pytest.raises(AuthError, match=INVALID_SESSION) as exc:
            await bouncer.exchange_code("c", NONCE)
    assert "aud" not in str(exc.value) and "cid" not in str(exc.value)  # пользователю — без деталей
    assert "BOUNCER_CLIENT_ID" in caplog.text and "cid" in caplog.text  # причина — в логе
    assert token not in caplog.text  # сам токен в лог не попадает


@pytest.mark.parametrize("aud", ["cid", ["other", "cid"]], ids=["строка", "список с нужным значением"])
async def test_exchange_code_accepts_audience(token_endpoint, aud):
    token_endpoint(json={"id_token": id_token(aud=aud, email="a@corp.io")})
    assert (await bouncer.exchange_code("c", NONCE)).username == "a@corp.io"


async def test_exchange_code_rejects_wrong_issuer_when_configured(token_endpoint, monkeypatch, caplog):
    monkeypatch.setattr(settings, "bouncer_issuer", "https://sso.example")
    token_endpoint(json={"id_token": id_token(email="a@corp.io", iss="https://evil.example")})
    with caplog.at_level("WARNING", logger="hmsrent.bouncer"):
        with pytest.raises(AuthError, match=INVALID_SESSION):
            await bouncer.exchange_code("c", NONCE)
    assert "https://evil.example" in caplog.text and "BOUNCER_ISSUER" in caplog.text


async def test_exchange_code_accepts_matching_issuer(token_endpoint, monkeypatch):
    monkeypatch.setattr(settings, "bouncer_issuer", "https://sso.example")
    token_endpoint(json={"id_token": id_token(email="a@corp.io", iss="https://sso.example")})
    assert (await bouncer.exchange_code("c", NONCE)).username == "a@corp.io"


async def test_exchange_code_missing_issuer_is_rejected_when_configured(token_endpoint, monkeypatch):
    monkeypatch.setattr(settings, "bouncer_issuer", "https://sso.example")
    token_endpoint(json={"id_token": id_token(email="a@corp.io")})
    with pytest.raises(AuthError, match=INVALID_SESSION):
        await bouncer.exchange_code("c", NONCE)


async def test_exchange_code_empty_issuer_setting_does_not_check_iss(token_endpoint):
    assert settings.bouncer_issuer == ""
    token_endpoint(json={"id_token": id_token(email="a@corp.io", iss="https://anything.example")})
    assert (await bouncer.exchange_code("c", NONCE)).username == "a@corp.io"


async def test_exchange_code_missing_exp_is_rejected(token_endpoint):
    token = jwt.encode({"nonce": NONCE, "email": "a@corp.io"}, "k", algorithm="HS256")
    token_endpoint(json={"id_token": token})
    with pytest.raises(AuthError, match="устарела"):
        await bouncer.exchange_code("c", NONCE)


async def test_exchange_code_no_identity_claims(token_endpoint):
    token_endpoint(json={"id_token": id_token(name="Аноним", email="  ")})
    with pytest.raises(AuthError, match="email или логин"):
        await bouncer.exchange_code("c", NONCE)


# Сбои токен-эндпоинта и мусор в ответе — AuthError, поэтому callback редиректит на /login, а не отдаёт 500.
async def test_exchange_code_garbage_id_token_is_auth_error(token_endpoint):
    token_endpoint(json={"id_token": "not-a-jwt"})
    with pytest.raises(AuthError):
        await bouncer.exchange_code("c", NONCE)


async def test_exchange_code_non_json_body_is_auth_error(token_endpoint):
    token_endpoint(content=b"<html>proxy error</html>")
    with pytest.raises(AuthError):
        await bouncer.exchange_code("c", NONCE)


@pytest.mark.parametrize("exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
async def test_exchange_code_network_error_is_auth_error(respx_mock, exc):
    respx_mock.post(TOKEN_URL).mock(side_effect=exc)
    with pytest.raises(AuthError):
        await bouncer.exchange_code("c", NONCE)


# ---------- Сквозной вход: /auth/bouncer/login -> /callback с настоящим exchange_code ----------

async def _start(client, api, nxt="/mine"):
    r = await client.get(api("/auth/bouncer/login"), params={"next": nxt})
    return jwt.decode(r.cookies[auth_routes.OAUTH_COOKIE], settings.secret_key, algorithms=["HS256"])


async def _callback(client, api, saved, **kw):
    return await client.get(api("/auth/bouncer/callback"), params={"code": "c", "state": saved["state"]})


async def test_login_flow_creates_user_and_clears_oauth_cookie(client, api, session, token_endpoint):
    saved = await _start(client, api, "/catalog")
    route = token_endpoint(json={"id_token": id_token(saved["nonce"], email="New@Corp.io", name="Новый")})
    r = await _callback(client, api, saved)
    assert r.status_code == 302 and r.headers["location"] == "/catalog"
    assert b"code=c" in route.calls.last.request.content
    assert any(settings.cookie_name in c for c in r.headers.get_list("set-cookie"))
    assert any(auth_routes.OAUTH_COOKIE in c and 'max-age=0' in c.lower() for c in r.headers.get_list("set-cookie"))
    u = await session.scalar(select(User).where(User.username == "new@corp.io"))
    assert (u.auth_source, u.role, u.display_name, u.email, u.is_active) == ("bouncer", "user", "Новый", "new@corp.io", True)
    assert u.last_login_at is not None and u.password_hash is None
    assert (await client.get(api("/auth/me"))).json()["user"]["username"] == "new@corp.io"


async def test_login_flow_second_login_updates_profile_and_revokes_admin(client, api, session, token_endpoint, make_user,
                                                                         admins_file):
    old = await make_user("x@corp.io", auth_source="bouncer", email="x@corp.io", role="admin", password=None,
                          display_name="Старое")
    admins_file("")  # из admins.txt убрали
    saved = await _start(client, api)
    token_endpoint(json={"id_token": id_token(saved["nonce"], email="x@corp.io", name="Новое")})
    r = await _callback(client, api, saved)
    assert r.headers["location"] == "/mine"
    await session.refresh(old)
    assert old.display_name == "Новое" and old.role == "user"
    assert len((await session.scalars(select(User))).all()) == 1  # дубликата не создано


async def test_login_flow_admin_from_admins_file(client, api, session, token_endpoint, admins_file):
    admins_file("boss@corp.io")
    saved = await _start(client, api)
    token_endpoint(json={"id_token": id_token(saved["nonce"], email="boss@corp.io")})
    await _callback(client, api, saved)
    assert (await session.scalar(select(User))).role == "admin"


@pytest.mark.parametrize("respond,message", [
    (dict(status=400, json={}), "отклонил"),
    (dict(status=200, json={}), "id_token"),
    (dict(status=200, json={"id_token": "EXPIRED"}), "устарела"),
    (dict(status=200, json={"id_token": "NONCE"}), "устарела"),
    (dict(status=200, json={"id_token": "AUD"}), "некорректна"),
    (dict(status=200, json={"id_token": "EMPTY"}), "email или логин"),
])
async def test_login_flow_auth_errors_redirect_to_login(client, api, session, token_endpoint, respond, message):
    saved = await _start(client, api)
    tokens = {"EXPIRED": id_token(saved["nonce"], exp=time.time() - 5, email="a@corp.io"),
              "NONCE": id_token("wrong", email="a@corp.io"), "AUD": id_token(saved["nonce"], aud="x", email="a@corp.io"), "EMPTY": id_token(saved["nonce"])}
    body = respond["json"]
    if body.get("id_token") in tokens:
        body = {"id_token": tokens[body["id_token"]]}
    token_endpoint(respond["status"], json=body)
    r = await _callback(client, api, saved)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")
    assert message in unquote(r.headers["location"])
    assert settings.cookie_name not in client.cookies
    assert (await session.scalars(select(User))).all() == []


async def test_login_flow_blocked_user_is_rejected(client, api, session, token_endpoint, make_user):
    await make_user("x@corp.io", auth_source="bouncer", password=None, is_active=False)
    saved = await _start(client, api)
    token_endpoint(json={"id_token": id_token(saved["nonce"], email="x@corp.io")})
    r = await _callback(client, api, saved)
    assert "отключена" in unquote(r.headers["location"]) and settings.cookie_name not in client.cookies


async def test_login_flow_state_cannot_be_replayed(client, api, token_endpoint):
    """Cookie со state удаляется после входа: повтор того же callback без неё — отказ."""
    saved = await _start(client, api)
    token_endpoint(json={"id_token": id_token(saved["nonce"], email="a@corp.io")})
    assert (await _callback(client, api, saved)).headers["location"] == "/mine"
    client.cookies.delete(auth_routes.OAUTH_COOKIE)
    assert (await _callback(client, api, saved)).headers["location"].startswith("/login?error=")


async def test_login_flow_saved_state_without_next_goes_home(client, api, token_endpoint):
    from app.core.security import create_oauth_state
    state, nonce, cookie = create_oauth_state("")
    client.cookies.set(auth_routes.OAUTH_COOKIE, cookie)
    token_endpoint(json={"id_token": id_token(nonce, email="a@corp.io")})
    r = await client.get(api("/auth/bouncer/callback"), params={"code": "c", "state": state})
    assert r.headers["location"] == "/"


async def test_login_flow_bouncer_down_redirects_to_login(client, api, respx_mock):
    saved = await _start(client, api)
    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    r = await _callback(client, api, saved)
    assert r.headers["location"].startswith("/login?error=")
