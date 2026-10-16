"""Вход и сессии: локальные админы, dev-вход, блокировка перебора, cookie, logout, /me, SSO-права из admins.txt,
защита старта в prod, Bouncer."""
import os
import time
from datetime import datetime, timedelta, timezone
from itertools import count

import jwt
import pytest
from sqlalchemy import func, select

from app.api.routes import auth as auth_routes
from app.core import admins
from app.core.config import settings
from app.core.security import create_session_token
from app.integrations.auth import bouncer
from app.integrations.auth.base import AuthResult
from app.main import app
from app.models import User, UserRole

ADMIN = UserRole.admin.value


@pytest.fixture(autouse=True)
def _reset_throttle():
    for store in (auth_routes._failed, auth_routes._failed_by_user):
        store.clear()
    yield
    for store in (auth_routes._failed, auth_routes._failed_by_user):
        store.clear()


@pytest.fixture
def admins_file(tmp_path, monkeypatch):
    """Подменяет источник списка админов на временный файл. write(*строки) пишет его заново."""
    path = tmp_path / "admins.txt"
    monkeypatch.setattr(admins, "_path", lambda: path)
    monkeypatch.setattr(admins, "_cache", (-1.0, frozenset()))
    tick = count(1_000_000_000, 10)  # разные mtime: кэш инвалидируется по mtime, а не по содержимому

    def write(*lines: str) -> None:
        path.write_text("\n".join(lines), encoding="utf-8")
        t = next(tick)
        os.utime(path, (t, t))
    return write


async def _login(client, username, password="pass12345", ip=None):
    """ip — адрес клиента для X-Forwarded-For (так его передаёт nginx); без него адрес берётся из соединения."""
    headers = {"X-Forwarded-For": ip} if ip else None
    return await client.post(settings.api_prefix + "/auth/login", json={"username": username, "password": password},
                             headers=headers)


# ---------- /auth/config ----------

async def test_config_reflects_settings(client, api, monkeypatch):
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    monkeypatch.setattr(settings, "auth_local_enabled", False)
    body = (await client.get(api("/auth/config"))).json()
    assert body["dev_enabled"] is True and body["local_enabled"] is False and body["bouncer_enabled"] is False


# ---------- Локальный вход ----------

async def test_local_login_ok_sets_session(client, make_user, session, api):
    user = await make_user("admin", role=ADMIN)
    r = await _login(client, "admin")
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "admin" and r.json()["user"]["role"] == "admin"
    me = await client.get(api("/auth/me"))  # cookie осела в клиенте и принимается
    assert me.status_code == 200 and me.json()["user"]["id"] == user.id
    await session.refresh(user)
    assert user.last_login_at is not None


async def test_login_cookie_flags(client, make_user, monkeypatch):
    await make_user("admin", role=ADMIN)
    cookie = (await _login(client, "admin")).headers["set-cookie"].lower()
    assert f"{settings.cookie_name}=" in cookie
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    assert f"max-age={settings.session_ttl_hours * 3600}" in cookie
    assert "secure" not in cookie
    monkeypatch.setattr(settings, "cookie_secure", True)
    assert "secure" in (await _login(client, "admin")).headers["set-cookie"].lower()


async def test_login_normalizes_username(client, make_user):
    await make_user("admin", role=ADMIN)
    assert (await _login(client, "  Admin ")).status_code == 200


async def test_login_wrong_password_and_unknown_user_look_the_same(client, make_user):
    await make_user("admin", role=ADMIN)
    bad_pwd = await _login(client, "admin", "wrong")
    unknown = await _login(client, "nobody", "wrong")
    assert bad_pwd.status_code == unknown.status_code == 401
    assert bad_pwd.json() == unknown.json()  # без подсказки, существует ли логин
    assert "set-cookie" not in bad_pwd.headers


async def test_login_inactive_user_rejected(client, make_user):
    await make_user("admin", role=ADMIN, is_active=False)
    assert (await _login(client, "admin")).status_code == 401


async def test_login_user_without_password_rejected(client, make_user):
    await make_user("nopass", password=None)
    assert (await _login(client, "nopass", "")).status_code == 401


async def test_login_validation(client, api):
    assert (await client.post(api("/auth/login"), json={"username": ""})).status_code == 422
    assert (await client.post(api("/auth/login"), json={})).status_code == 422


# ---------- Блокировка перебора ----------

async def test_lockout_after_max_attempts(client, make_user):
    await make_user("admin", role=ADMIN)
    for _ in range(settings.login_max_attempts):
        assert (await _login(client, "admin", "wrong")).status_code == 401
    assert (await _login(client, "admin", "wrong")).status_code == 429
    assert (await _login(client, "admin")).status_code == 429  # даже верный пароль, пока идёт блокировка


async def test_lockout_is_per_username(client, make_user):
    await make_user("admin", role=ADMIN)
    await make_user("other", role=ADMIN)
    for _ in range(settings.login_max_attempts):
        await _login(client, "admin", "wrong")
    assert (await _login(client, "other")).status_code == 200


async def test_lockout_expires(client, make_user):
    await make_user("admin", role=ADMIN)
    for _ in range(settings.login_max_attempts):
        await _login(client, "admin", "wrong")
    old = time.time() - settings.login_lock_minutes * 60 - 1
    for store in (auth_routes._failed, auth_routes._failed_by_user):  # попытки «состарились»
        for key in list(store):
            store[key] = [old] * len(store[key])
    assert (await _login(client, "admin")).status_code == 200


async def test_success_resets_failed_counter(client, make_user):
    await make_user("admin", role=ADMIN)
    for _ in range(settings.login_max_attempts - 1):
        await _login(client, "admin", "wrong")
    assert (await _login(client, "admin")).status_code == 200
    for _ in range(settings.login_max_attempts - 1):  # счётчик начался заново
        assert (await _login(client, "admin", "wrong")).status_code == 401


async def test_lockout_is_per_address_so_stranger_cannot_lock_admin_out(client, make_user):
    """Перебор с чужого адреса блокирует только этот адрес, настоящий админ входит со своего."""
    await make_user("admin", role=ADMIN)
    for _ in range(settings.login_max_attempts):
        assert (await _login(client, "admin", "wrong", ip="203.0.113.9")).status_code == 401
    assert (await _login(client, "admin", "wrong", ip="203.0.113.9")).status_code == 429
    assert (await _login(client, "admin", ip="198.51.100.7")).status_code == 200


async def test_lockout_uses_last_forwarded_address(client, make_user):
    """Клиент может подписать X-Forwarded-For своим значением, но последний адрес дописывает nginx."""
    await make_user("admin", role=ADMIN)
    for i in range(settings.login_max_attempts):
        await _login(client, "admin", "wrong", ip=f"10.0.0.{i}, 203.0.113.9")  # «чужие» адреса спереди
    assert (await _login(client, "admin", ip="1.2.3.4, 203.0.113.9")).status_code == 429


async def test_username_wide_cap_stops_spoofed_addresses(client, make_user):
    """Если адрес подделан и каждый раз новый, перебор упирается в общий потолок на логин."""
    await make_user("admin", role=ADMIN)
    cap = settings.login_max_attempts * auth_routes.LOGIN_USER_LIMIT_FACTOR
    for i in range(cap):
        assert (await _login(client, "admin", "wrong", ip=f"10.1.{i // 250}.{i % 250}")).status_code == 401
    assert (await _login(client, "admin", ip="198.51.100.7")).status_code == 429


async def test_expired_throttle_keys_are_dropped(client, make_user):
    await make_user("admin", role=ADMIN)
    await _login(client, "admin", "wrong", ip="203.0.113.9")
    old = time.time() - settings.login_lock_minutes * 60 - 1
    for store in (auth_routes._failed, auth_routes._failed_by_user):
        for key in list(store):
            store[key] = [old]
    await _login(client, "admin", "wrong", ip="203.0.113.9")  # проверка выбрасывает устаревшие попытки
    assert [len(v) for v in auth_routes._failed.values()] == [1]
    assert [len(v) for v in auth_routes._failed_by_user.values()] == [1]


async def test_lockout_applies_to_unknown_usernames_too(client):
    for _ in range(settings.login_max_attempts):
        await _login(client, "ghost", "x")
    assert (await _login(client, "ghost", "x")).status_code == 429


# ---------- Переключатели local / dev ----------

async def test_local_disabled_rejects_local_admin(client, make_user, monkeypatch):
    await make_user("admin", role=ADMIN)
    monkeypatch.setattr(settings, "auth_local_enabled", False)
    r = await _login(client, "admin")
    assert r.status_code == 401 and "set-cookie" not in r.headers


async def test_local_disabled_dev_enabled_cannot_hijack_local_account(client, make_user, monkeypatch):
    """Логин локального админа нельзя «перехватить» через dev-вход без пароля."""
    await make_user("admin", role=ADMIN)
    monkeypatch.setattr(settings, "auth_local_enabled", False)
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    assert (await _login(client, "admin", "")).status_code == 401


async def test_dev_enabled_wrong_password_for_local_admin_is_rejected(client, make_user, monkeypatch):
    await make_user("admin", role=ADMIN)
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    assert (await _login(client, "admin", "wrong")).status_code == 401
    assert (await _login(client, "admin")).status_code == 200


async def test_dev_login_disabled_by_default(client, session):
    assert settings.auth_dev_enabled is False
    r = await _login(client, "petya", "")
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert await session.scalar(select(User).where(User.username == "petya")) is None


async def test_dev_login_creates_regular_user(client, api, session, monkeypatch):
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    r = await _login(client, "Petya", "")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "user" and r.json()["user"]["auth_source"] == "dev"
    assert (await client.get(api("/admin/stats"))).status_code == 403
    await _login(client, "petya", "")  # повторный вход не плодит дубликатов
    assert await session.scalar(select(func.count()).select_from(User)) == 1


async def test_dev_login_admin_username_is_admin(client, api, monkeypatch):
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    assert (await _login(client, "admin", "")).json()["user"]["role"] == "admin"
    assert (await client.get(api("/admin/stats"))).status_code == 200


async def test_dev_login_admin_by_admins_file(client, admins_file, monkeypatch):
    admins_file("boss@corp.io  # комментарий", "", "# просто комментарий")
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    assert (await _login(client, "Boss@Corp.io", "")).json()["user"]["role"] == "admin"
    assert (await _login(client, "other@corp.io", "")).json()["user"]["role"] == "user"


async def test_dev_login_blocked_user_and_blank_name(client, make_user, monkeypatch):
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    await make_user("blocked", auth_source="dev", is_active=False, password=None)
    assert (await _login(client, "blocked", "")).status_code == 401
    assert (await _login(client, "   ", "")).status_code == 401


# ---------- logout и /me ----------

async def test_logout_clears_cookie(client, make_user, api):
    await make_user("admin", role=ADMIN)
    await _login(client, "admin")
    r = await client.post(api("/auth/logout"))
    assert r.status_code == 204
    assert f"{settings.cookie_name}=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    assert (await client.get(api("/auth/me"))).status_code == 401


async def test_me_without_or_with_broken_cookie(client, make_user, api):
    user = await make_user("emp")
    assert (await client.get(api("/auth/me"))).status_code == 401
    now = datetime.now(timezone.utc)
    good = {"sub": str(user.id), "usr": "emp", "role": "user", "exp": now + timedelta(hours=1)}
    for bad in (
        "garbage",
        jwt.encode(good, "another-secret-another-secret-123", algorithm="HS256"),            # чужая подпись
        jwt.encode({**good, "exp": now - timedelta(seconds=5)}, settings.secret_key, algorithm="HS256"),  # истёк
    ):
        client.cookies.set(settings.cookie_name, bad)
        r = await client.get(api("/auth/me"))
        assert r.status_code == 401, bad


async def test_me_signed_token_without_sub_is_401(client, api):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    client.cookies.set(settings.cookie_name, jwt.encode({"exp": exp}, settings.secret_key, algorithm="HS256"))
    assert (await client.get(api("/auth/me"))).status_code == 401


async def test_me_unknown_user_and_unsigned_token(client, api):
    client.cookies.set(settings.cookie_name, create_session_token(999, "ghost", "user"))
    assert (await client.get(api("/auth/me"))).status_code == 401
    client.cookies.set(settings.cookie_name, jwt.encode({"sub": "1"}, key=None, algorithm="none"))
    assert (await client.get(api("/auth/me"))).status_code == 401


# ---------- SSO-права из config/admins.txt (проверяются на каждом запросе) ----------

@pytest.mark.parametrize("source", ["bouncer", "microsoft", "dev"])
async def test_sso_admin_granted_and_revoked_by_list(client, login, make_user, admins_file, api, source):
    admins_file("boss@corp.io")
    login(await make_user("boss@corp.io", auth_source=source, email="boss@corp.io", password=None))  # в БД роль user
    assert (await client.get(api("/admin/stats"))).status_code == 200
    assert (await client.get(api("/auth/me"))).json()["user"]["role"] == "admin"
    admins_file("someone-else@corp.io")  # убрали из списка — права пропали без повторного входа
    assert (await client.get(api("/admin/stats"))).status_code == 403
    assert (await client.get(api("/auth/me"))).json()["user"]["role"] == "user"
    admins_file("BOSS@corp.io")  # вернули (регистр не важен)
    assert (await client.get(api("/admin/stats"))).status_code == 200


async def test_sso_admin_role_in_db_is_not_enough(client, login, make_user, admins_file, api):
    """Роль admin, записанная в БД SSO-пользователю, не действует, если почты нет в списке."""
    admins_file("nobody@corp.io")
    login(await make_user("x@corp.io", auth_source="bouncer", email="x@corp.io", role=ADMIN, password=None))
    assert (await client.get(api("/admin/stats"))).status_code == 403


async def test_sso_user_matched_by_username_when_no_email(client, login, make_user, admins_file, api):
    admins_file("boss@corp.io")
    login(await make_user("boss@corp.io", auth_source="bouncer", password=None))
    assert (await client.get(api("/admin/stats"))).status_code == 200


async def test_dev_user_named_admin_is_admin_without_list(client, login, make_user, admins_file, api):
    admins_file()
    login(await make_user("admin", auth_source="dev", password=None))
    assert (await client.get(api("/admin/stats"))).status_code == 200


async def test_local_admin_not_governed_by_list(client, login, make_user, admins_file, api):
    admins_file("someone@corp.io")
    login(await make_user("localboss", role=ADMIN))
    assert (await client.get(api("/admin/stats"))).status_code == 200
    # и локальный user, чья «почта» есть в списке, админом не становится
    admins_file("emp@corp.io")
    client.cookies.clear()
    login(await make_user("emp", email="emp@corp.io"))
    assert (await client.get(api("/admin/stats"))).status_code == 403


def test_admins_file_parsing_and_missing_file(admins_file, tmp_path, monkeypatch):
    admins_file("# шапка", "A@x.io", "  b@x.io   # коммент ", "", "   ")
    assert admins.admin_emails() == {"a@x.io", "b@x.io"}
    assert admins.is_admin_email("A@X.IO") and not admins.is_admin_email("c@x.io")
    assert not admins.is_admin_email(None) and not admins.is_admin_email("")
    monkeypatch.setattr(admins, "_path", lambda: tmp_path / "missing.txt")
    assert admins.admin_emails() == frozenset() and not admins.is_admin_email("a@x.io")


# ---------- Продовые запреты в lifespan ----------

async def test_prod_forbids_dev_auth(monkeypatch):
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "auth_dev_enabled", True)
    monkeypatch.setattr(settings, "secret_key", "a-real-long-secret-for-prod-1234567")
    with pytest.raises(RuntimeError, match="AUTH_DEV_ENABLED"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.parametrize("key", ["change-me-please", "change-me"])
async def test_prod_forbids_default_secret_key(monkeypatch, key):
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "auth_dev_enabled", False)
    monkeypatch.setattr(settings, "secret_key", key)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        async with app.router.lifespan_context(app):
            pass


# ---------- Bouncer ----------

async def test_bouncer_login_disabled_returns_404(client, api):
    assert (await client.get(api("/auth/bouncer/login"))).status_code == 404


@pytest.fixture
def bouncer_on(monkeypatch):
    monkeypatch.setattr(settings, "bouncer_client_id", "cid")
    monkeypatch.setattr(settings, "bouncer_client_secret", "sec")
    monkeypatch.setattr(settings, "bouncer_authorize_url", "https://sso.example/authorize")


@pytest.mark.parametrize("nxt,expected", [("/catalog", "/catalog"), ("//evil.com", "/"), ("https://evil.com", "/")])
async def test_bouncer_login_redirect_and_open_redirect_guard(client, api, bouncer_on, nxt, expected):
    r = await client.get(api("/auth/bouncer/login"), params={"next": nxt})
    assert r.status_code == 302 and r.headers["location"].startswith("https://sso.example/authorize?")
    cookie = r.cookies[auth_routes.OAUTH_COOKIE]
    saved = jwt.decode(cookie, settings.secret_key, algorithms=["HS256"])
    assert saved["next"] == expected and f"state={saved['state']}" in r.headers["location"]
    assert "httponly" in r.headers["set-cookie"].lower()


async def _start_oauth(client, api):
    r = await client.get(api("/auth/bouncer/login"), params={"next": "/mine"})
    return jwt.decode(r.cookies[auth_routes.OAUTH_COOKIE], settings.secret_key, algorithms=["HS256"])


@pytest.mark.parametrize("params", [{}, {"error": "access_denied"}, {"code": "c", "state": "wrong"}])
async def test_bouncer_callback_failures_redirect_to_login(client, api, bouncer_on, params):
    await _start_oauth(client, api)
    r = await client.get(api("/auth/bouncer/callback"), params=params)
    assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")
    assert settings.cookie_name not in client.cookies


async def test_bouncer_callback_without_state_cookie(client, api, bouncer_on):
    r = await client.get(api("/auth/bouncer/callback"), params={"code": "c", "state": "s"})
    assert r.status_code == 302 and r.headers["location"].startswith("/login?error=")


async def test_bouncer_callback_success_creates_user_and_session(client, api, bouncer_on, monkeypatch, admins_file):
    admins_file("sso@corp.io")
    seen = {}

    async def fake_exchange(code, nonce):
        seen.update(code=code, nonce=nonce)
        return AuthResult(username="sso@corp.io", display_name="Sso", email="sso@corp.io", is_admin=True)
    monkeypatch.setattr(bouncer, "exchange_code", fake_exchange)

    saved = await _start_oauth(client, api)
    r = await client.get(api("/auth/bouncer/callback"), params={"code": "abc", "state": saved["state"]})
    assert r.status_code == 302 and r.headers["location"] == "/mine"
    assert seen == {"code": "abc", "nonce": saved["nonce"]}
    me = (await client.get(api("/auth/me"))).json()["user"]
    assert me["username"] == "sso@corp.io" and me["auth_source"] == "bouncer" and me["role"] == "admin"


async def test_bouncer_callback_cannot_take_over_local_account(client, api, bouncer_on, monkeypatch, make_user):
    await make_user("admin", role=ADMIN)

    async def fake_exchange(code, nonce):
        return AuthResult(username="admin", display_name="Admin", is_admin=True)
    monkeypatch.setattr(bouncer, "exchange_code", fake_exchange)
    saved = await _start_oauth(client, api)
    r = await client.get(api("/auth/bouncer/callback"), params={"code": "c", "state": saved["state"]})
    assert r.headers["location"].startswith("/login?error=")
    assert settings.cookie_name not in client.cookies


@pytest.mark.parametrize("sub", ["abc", "", None, "1.5"])
async def test_me_signed_token_with_garbage_sub_is_401(client, api, sub):
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    client.cookies.set(settings.cookie_name, jwt.encode({"sub": sub, "exp": exp}, settings.secret_key, algorithm="HS256"))
    assert (await client.get(api("/auth/me"))).status_code == 401
