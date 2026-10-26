"""ПК, выданные отделу мимо портала (в Insight «Используется», «Команда-получатель» — отдел): GET /bookings/external."""
from datetime import date

import pytest

from app.models import UserRole


@pytest.fixture
async def env(make_user, make_department, make_computer, make_pool):
    eco, qa = await make_department("Product Eco Department"), await make_department("QA")
    pool = await make_pool("ECO Builder Studio")
    emp = await make_user("emp", department=eco, display_name="Эко Сотрудник")
    mate = await make_user("mate", department=eco)
    other = await make_user("other", department=qa)
    nodept = await make_user("nodept")
    mk = lambda name, **kw: make_computer(name, pool=pool, **kw)  # noqa: E731
    await mk("A10", status="in_use", department_id=eco.id, usage_until=date(2026, 12, 31))
    await mk("A9", status="in_use", department_id=eco.id)
    await mk("A20", status="in_use", department_id=qa.id)  # чужой отдел
    await mk("A30", status="available", department_id=eco.id)  # не занят
    await mk("A40", status="booked", department_id=eco.id)  # занят через портал: это обычная бронь
    await mk("A50", status="in_use", department_id=eco.id, is_archived=True)
    await mk("A60", status="in_use", department_id=None)
    await mk("vm-1", status="in_use", department_id=eco.id, is_virtual=True)
    return type("Env", (), dict(emp=emp, mate=mate, other=other, nodept=nodept, eco=eco))


async def names(client, api):
    r = await client.get(api("/bookings/external"))
    assert r.status_code == 200, r.text
    return [x["computer"]["name"] for x in r.json()]


async def test_team_sees_computers_given_to_its_department_outside_portal(client, api, login, env):
    login(env.emp)
    assert await names(client, api) == ["A9", "A10"]  # естественный порядок; чужие, свободные, брони, архив, ВМ не попадают
    row = (await client.get(api("/bookings/external"))).json()[1]
    assert (row["department"]["name"], row["usage_until"]) == ("Product Eco Department", "2026-12-31")
    assert "order_number" not in row


async def test_colleague_from_same_department_sees_the_same(client, api, login, env):
    login(env.mate)
    assert await names(client, api) == ["A9", "A10"]


async def test_other_department_sees_only_its_own(client, api, login, env):
    login(env.other)
    assert await names(client, api) == ["A20"]


async def test_employee_without_department_sees_nothing(client, api, login, env):
    login(env.nodept)
    assert await names(client, api) == []


async def test_requires_login(client, api, env):
    assert (await client.get(api("/bookings/external"))).status_code == 401


async def test_admin_in_view_mode_sees_what_employee_sees(client, api, login, env, make_user):
    admin = await make_user("boss", role=UserRole.admin.value)
    login(admin)
    assert await names(client, api) == []  # у администратора своего отдела нет
    assert (await client.post(api("/auth/view-as"), json={"user_id": env.emp.id})).status_code == 200
    assert await names(client, api) == ["A9", "A10"]
