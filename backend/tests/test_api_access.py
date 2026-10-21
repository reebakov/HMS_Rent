"""Матрица доступа: все маршруты реального роутера × (аноним, сотрудник, исполнитель, админ).

Маршруты берутся из app.main.app.routes, поэтому новый эндпоинт без авторизации сразу покраснеет
(его надо либо защитить, либо осознанно добавить в ANON_OK).
"""
import re

import jwt
import pytest
from starlette.routing import Route

from app.core.config import settings
from app.main import app
from app.models import UserRole

P = settings.api_prefix

# Единственные маршруты, доступные без входа. Всё остальное для анонима обязано отвечать 401.
ANON_OK = {
    ("GET", "/api/health"),
    ("GET", "/api/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/api/openapi.json"),
    ("GET", "/redoc"),
    ("GET", f"{P}/auth/config"),
    ("POST", f"{P}/auth/login"),
    ("POST", f"{P}/auth/logout"),
    ("GET", f"{P}/auth/bouncer/login"),
    ("GET", f"{P}/auth/bouncer/callback"),
}


def _all_routes() -> list[tuple[str, str]]:
    out = []
    for r in app.routes:
        if isinstance(r, Route):
            out += [(m, r.path) for m in sorted(r.methods - {"HEAD", "OPTIONS"})]
    return sorted(out)


ALL = _all_routes()
PROTECTED = [r for r in ALL if r not in ANON_OK]
ADMIN = [r for r in PROTECTED if r[1].startswith(f"{P}/admin")]
EXECUTOR = [r for r in PROTECTED if r[1].startswith(f"{P}/executor")]
EMPLOYEE = [r for r in PROTECTED if r not in ADMIN and r not in EXECUTOR]


def _call(c, method: str, path: str):
    url = re.sub(r"\{[^}]+\}", "1", path)  # path-параметры -> 1
    return c.request(method, url, json={} if method in {"POST", "PUT", "PATCH"} else None)


def _ids(routes):
    return [f"{m} {p}" for m, p in routes]


def test_route_discovery_sanity():
    """Страховка от пустой параметризации и от устаревших записей белого списка."""
    assert len(ADMIN) >= 20 and len(EMPLOYEE) >= 8 and len(EXECUTOR) >= 3
    assert ANON_OK <= set(ALL), f"в белом списке нет таких маршрутов: {ANON_OK - set(ALL)}"
    # все admin-эндпоинты живут под /admin: нет «админских» ручек вне префикса
    assert not [p for _, p in EMPLOYEE if "/admin" in p]


@pytest.mark.parametrize("method,path", PROTECTED, ids=_ids(PROTECTED))
async def test_anonymous_gets_401(client, method, path):
    assert (await _call(client, method, path)).status_code == 401


@pytest.mark.parametrize("method,path", sorted(ANON_OK), ids=_ids(sorted(ANON_OK)))
async def test_whitelisted_open_for_anonymous(client, method, path):
    assert (await _call(client, method, path)).status_code not in (401, 403)


@pytest.mark.parametrize("method,path", ADMIN, ids=_ids(ADMIN))
async def test_employee_gets_403_on_admin_routes(client, login, make_user, method, path):
    login(await make_user("emp"))
    assert (await _call(client, method, path)).status_code == 403


@pytest.mark.parametrize("method,path", EXECUTOR, ids=_ids(EXECUTOR))
async def test_employee_gets_403_on_executor_routes(client, login, make_user, method, path):
    login(await make_user("emp"))
    assert (await _call(client, method, path)).status_code == 403


@pytest.mark.parametrize("method,path", EXECUTOR + EMPLOYEE, ids=_ids(EXECUTOR + EMPLOYEE))
async def test_executor_allowed_on_executor_and_regular_routes(client, login, make_user, method, path):
    login(await make_user("worker", role=UserRole.executor.value))
    assert (await _call(client, method, path)).status_code not in (401, 403)


@pytest.mark.parametrize("method,path", ADMIN, ids=_ids(ADMIN))
async def test_executor_gets_403_on_admin_routes(client, login, make_user, method, path):
    login(await make_user("worker", role=UserRole.executor.value))
    assert (await _call(client, method, path)).status_code == 403


@pytest.mark.parametrize("method,path", EMPLOYEE, ids=_ids(EMPLOYEE))
async def test_employee_allowed_on_regular_routes(client, login, make_user, method, path):
    login(await make_user("emp"))
    assert (await _call(client, method, path)).status_code not in (401, 403)


@pytest.mark.parametrize("method,path", PROTECTED, ids=_ids(PROTECTED))
async def test_admin_passes_everywhere(client, login, make_user, method, path):
    login(await make_user("boss", role=UserRole.admin.value))
    assert (await _call(client, method, path)).status_code not in (401, 403)


async def test_role_claim_in_token_is_ignored(client, make_user, api):
    """Права берутся из БД, а не из поля role в JWT: подделать role=admin нельзя даже с верной подписью."""
    user = await make_user("emp")
    forged = jwt.encode({"sub": str(user.id), "usr": "emp", "role": "admin"}, settings.secret_key, algorithm="HS256")
    client.cookies.set(settings.cookie_name, forged)
    assert (await client.get(api("/admin/stats"))).status_code == 403


async def test_demoted_admin_loses_access_immediately(client, login, make_user, session, api):
    """Токен выдан админу, потом роль в БД сменили — следующий же запрос уже 403."""
    user = await make_user("boss", role=UserRole.admin.value)
    login(user)
    assert (await client.get(api("/admin/stats"))).status_code == 200
    user.role = UserRole.user.value
    await session.commit()
    assert (await client.get(api("/admin/stats"))).status_code == 403


async def test_deactivated_user_cannot_use_old_token(client, login, make_user, session, api):
    user = await make_user("emp")
    login(user)
    assert (await client.get(api("/catalog/summary"))).status_code == 200
    user.is_active = False
    await session.commit()
    assert (await client.get(api("/catalog/summary"))).status_code == 401
