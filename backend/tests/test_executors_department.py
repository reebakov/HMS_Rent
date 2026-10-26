"""Сотрудники отдела исполнителей (код EXECUTORS_DEPARTMENT_CODE) — исполнители без записи в executors.txt."""
import pytest

from app.core.config import settings
from app.integrations.auth.base import AuthResult
from app.services import auth as auth_service


@pytest.fixture
async def hms(make_department):
    return await make_department("Hardware Maintenance Support", code="HMS")


async def sso_user(make_user, name="worker", **kw):
    return await make_user(name, auth_source="bouncer", email=f"{name}@corp.test", password=None, **kw)


async def test_department_member_is_executor(client, api, login, make_user, hms):
    login(await sso_user(make_user, department=hms))
    assert (await client.get(api("/auth/me"))).json()["user"]["role"] == "executor"
    assert (await client.get(api("/executor/orders"))).status_code == 200


async def test_other_department_stays_regular_employee(client, api, login, make_user, make_department):
    login(await sso_user(make_user, department=await make_department("QA", code="QA")))
    assert (await client.get(api("/auth/me"))).json()["user"]["role"] == "user"
    assert (await client.get(api("/executor/orders"))).status_code == 403


async def test_employee_without_department_stays_regular(client, api, login, make_user):
    login(await sso_user(make_user))
    assert (await client.get(api("/executor/orders"))).status_code == 403


async def test_code_comparison_ignores_case_and_spaces(client, api, login, make_user, make_department):
    login(await sso_user(make_user, department=await make_department("Support", code=" hms ")))
    assert (await client.get(api("/executor/orders"))).status_code == 200


async def test_rule_is_off_when_code_is_empty(client, api, login, make_user, hms, monkeypatch):
    monkeypatch.setattr(settings, "executors_department_code", "")
    login(await sso_user(make_user, department=hms))
    assert (await client.get(api("/executor/orders"))).status_code == 403


async def test_moving_to_department_takes_effect_immediately(client, api, login, make_user, hms, make_department, session):
    user = await sso_user(make_user, department=await make_department("QA", code="QA"))
    login(user)
    assert (await client.get(api("/executor/orders"))).status_code == 403
    user.department_id = hms.id
    await session.commit()
    assert (await client.get(api("/executor/orders"))).status_code == 200


async def test_executor_by_department_has_no_admin_rights(client, api, login, make_user, hms):
    login(await sso_user(make_user, department=hms))
    assert (await client.get(api("/admin/users"))).status_code == 403


async def test_admin_list_shows_executor_role(client, api, login, make_user, hms):
    await sso_user(make_user, "worker", department=hms)
    login(await make_user("boss", role="admin"))
    rows = {r["username"]: r["role"] for r in (await client.get(api("/admin/users"))).json()}
    assert rows["worker"] == "executor"


async def test_sso_login_of_prepared_employee_returns_executor_role(session, make_user, hms):
    """Сотрудника завели заранее с отделом: уже при первом входе он исполнитель (ответ входа без перезагрузки)."""
    await make_user("worker@corp.test", auth_source="microsoft", email="worker@corp.test", password=None, department=hms)
    result = AuthResult(username="worker@corp.test", display_name="Worker", email="worker@corp.test", avatar_url=None, is_admin=False)
    user = await auth_service.upsert_sso_user(session, result, "bouncer")
    assert user.role == "executor"
