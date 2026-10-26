"""Режим «Открыть как пользователь»: администратор смотрит портал глазами сотрудника, только на чтение."""
import pytest

from app.api.deps import VIEW_AS_COOKIE
from app.core.config import settings
from app.core.security import create_session_token, create_view_as_token
from app.models import UserRole
from tests.sync_fakes import add_booking


@pytest.fixture
async def env(make_user, make_department, make_computer, make_pool, session):
    dept, other = await make_department("QA"), await make_department("Ops")
    pool = await make_pool("Main")
    admin = await make_user("boss", role=UserRole.admin.value, display_name="Босс Админов")
    emp = await make_user("emp", department=dept, display_name="Иван Иванов")
    stranger = await make_user("stranger", department=other)
    comp = await make_computer("A001", pool=pool, status="booked")
    await add_booking(session, comp, emp, dept)
    return type("Env", (), dict(admin=admin, emp=emp, stranger=stranger, dept=dept))


async def start(client, api, user_id):
    return await client.post(api("/auth/view-as"), json={"user_id": user_id})


async def test_admin_sees_portal_as_employee(client, api, login, env):
    login(env.admin)
    r = await start(client, api, env.emp.id)
    assert r.status_code == 200
    assert (r.json()["user"]["username"], r.json()["view_as_by"]["display_name"]) == ("emp", "Босс Админов")
    me = (await client.get(api("/auth/me"))).json()
    assert (me["user"]["username"], me["user"]["role"], me["view_as_by"]["id"]) == ("emp", "user", env.admin.id)
    assert [b["computer"]["name"] for b in (await client.get(api("/bookings/my"))).json()] == ["A001"]


async def test_admin_pages_are_closed_while_viewing_as_employee(client, api, login, env):
    login(env.admin)
    assert (await client.get(api("/admin/users"))).status_code == 200
    await start(client, api, env.emp.id)
    assert (await client.get(api("/admin/users"))).status_code == 403  # так видит сотрудник


@pytest.mark.parametrize("method, path", [("post", "/bookings/1/return"), ("patch", "/admin/users/1"), ("post", "/notifications/read-all"),
                                          ("post", "/vms/1/release")])
async def test_view_mode_is_read_only(client, api, login, env, method, path):
    login(env.admin)
    await start(client, api, env.emp.id)
    r = await getattr(client, method)(api(path))
    assert r.status_code == 403 and "Режим просмотра" in r.json()["detail"]


async def test_stop_returns_to_admin_and_allows_actions(client, api, login, env):
    login(env.admin)
    await start(client, api, env.emp.id)
    r = await client.delete(api("/auth/view-as"))
    assert r.status_code == 200 and (r.json()["user"]["username"], r.json()["view_as_by"]) == ("boss", None)
    me = (await client.get(api("/auth/me"))).json()
    assert (me["user"]["username"], me["view_as_by"]) == ("boss", None)
    assert (await client.get(api("/admin/users"))).status_code == 200


async def test_switch_to_another_employee_while_viewing(client, api, login, env):
    login(env.admin)
    await start(client, api, env.emp.id)
    assert (await start(client, api, env.stranger.id)).status_code == 200  # переключение не блокируется режимом просмотра
    assert (await client.get(api("/auth/me"))).json()["user"]["username"] == "stranger"


@pytest.mark.parametrize("who, code", [("emp", 403), ("missing", 404), ("self", 409), ("inactive", 404)])
async def test_start_validation(client, api, login, env, make_user, who, code):
    login(env.admin if who != "emp" else env.emp)
    target = {"emp": env.stranger.id, "missing": 999999, "self": env.admin.id,
              "inactive": (await make_user("gone", is_active=False)).id}[who]
    assert (await start(client, api, target)).status_code == code


async def test_anonymous_cannot_start(client, api, env):
    assert (await start(client, api, env.emp.id)).status_code == 401


async def test_view_cookie_of_demoted_admin_is_ignored(client, api, session, env):
    """Cookie режима просмотра действует только пока вошедший — администратор, который её получил."""
    client.cookies.set(settings.cookie_name, create_session_token(env.stranger.id, "stranger", "user"))
    client.cookies.set(VIEW_AS_COOKIE, create_view_as_token(env.admin.id, env.emp.id))
    me = (await client.get(api("/auth/me"))).json()
    assert (me["user"]["username"], me["view_as_by"]) == ("stranger", None)


async def test_view_cookie_of_other_admin_is_ignored(client, api, login, env, make_user):
    other = await make_user("boss2", role=UserRole.admin.value)
    login(env.admin)
    client.cookies.set(VIEW_AS_COOKIE, create_view_as_token(other.id, env.emp.id))
    assert (await client.get(api("/auth/me"))).json()["user"]["username"] == "boss"


async def test_view_cookie_with_garbage_is_ignored(client, api, login, env):
    login(env.admin)
    client.cookies.set(VIEW_AS_COOKIE, "not-a-token")
    assert (await client.get(api("/auth/me"))).json()["user"]["username"] == "boss"


async def test_deactivated_target_ends_view_mode(client, api, login, env, session):
    login(env.admin)
    await start(client, api, env.emp.id)
    env.emp.is_active = False
    await session.commit()
    assert (await client.get(api("/auth/me"))).json()["user"]["username"] == "boss"


async def test_logout_clears_view_mode(client, api, login, env):
    login(env.admin)
    await start(client, api, env.emp.id)
    assert (await client.post(api("/auth/logout"))).status_code == 204
    assert VIEW_AS_COOKIE not in client.cookies


async def test_start_response_has_effective_role_not_stale_one_from_db(client, api, login, env, make_user, make_department):
    """Регрессия: ответ входа в режим просмотра отдавал роль из БД, и у исполнителя по отделу не было вкладок исполнителя."""
    hms = await make_department("Hardware Maintenance Support", code="HMS")
    worker = await make_user("worker@corp.test", auth_source="bouncer", email="worker@corp.test", password=None, department=hms)
    assert worker.role == "user"  # в БД роль не обновлялась: сотрудник ещё не входил
    login(env.admin)
    r = await start(client, api, worker.id)
    assert r.json()["user"]["role"] == "executor"
    assert (await client.get(api("/auth/me"))).json()["user"]["role"] == "executor"
