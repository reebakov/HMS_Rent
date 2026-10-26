"""ПК, выданные отделу мимо портала (в Insight «Используется», «Команда-получатель» — отдел): GET /bookings/external."""
from datetime import date

import pytest
from sqlalchemy import select

from app.models import Booking, BookingStatus, Computer, ComputerStatus, ServiceRequest, UserRole
from tests.test_service_requests import sd  # noqa: F401 — Service Desk подключён, клиент Jira подменён


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


# ---------- действия: проблема и возврат ----------

async def computer_id(session, name):
    return (await session.scalar(select(Computer).where(Computer.name == name))).id


async def test_problem_for_external_computer_goes_to_jira_without_booking(client, api, login, env, session, sd):  # noqa: F811
    login(env.emp)
    cid = await computer_id(session, "A10")
    r = await client.post(api("/requests"), json={"computer_id": cid, "message": "Не включается"})
    assert r.status_code == 201, r.text
    assert (r.json()["computer_id"], r.json()["booking_id"], r.json()["vm_id"]) == (cid, None, None)
    assert "A10" in r.json()["summary"] and "выдан вне портала" in r.json()["summary"]
    description = sd.created[0][2]
    assert description.startswith("Не включается") and "Команда-получатель: Product Eco Department" in description
    # заявку видит вся команда, чужой отдел — нет
    login(env.mate)
    assert [x["computer_id"] for x in (await client.get(api("/requests/my"))).json()] == [cid]
    login(env.other)
    assert (await client.get(api("/requests/my"))).json() == []


@pytest.mark.parametrize("who, code", [("other", 403), ("nodept", 403)])
async def test_problem_for_foreign_external_computer_is_forbidden(client, api, login, env, session, sd, who, code):  # noqa: F811
    login(getattr(env, who))
    r = await client.post(api("/requests"), json={"computer_id": await computer_id(session, "A10"), "message": "Не включается"})
    assert r.status_code == code


@pytest.mark.parametrize("name", ["A30", "A40", "vm-1", "A50"], ids=["free", "booked", "virtual", "archived"])
async def test_problem_only_for_computers_given_to_the_team_outside_portal(client, api, login, env, session, sd, name):  # noqa: F811
    login(env.emp)
    r = await client.post(api("/requests"), json={"computer_id": await computer_id(session, name), "message": "Не включается"})
    assert r.status_code in (404, 409)


async def test_problem_needs_exactly_one_target(client, api, login, env, session):
    login(env.emp)
    cid = await computer_id(session, "A10")
    for body in ({"message": "Не включается"}, {"computer_id": cid, "booking_id": 1, "message": "Не включается"}):
        assert (await client.post(api("/requests"), json=body)).status_code == 422


async def test_executor_sees_problem_about_external_computer_without_order_number(client, api, login, env, session, sd, make_user):  # noqa: F811
    login(env.emp)
    cid = await computer_id(session, "A10")
    await client.post(api("/requests"), json={"computer_id": cid, "message": "Не включается"})
    login(await make_user("worker", role=UserRole.executor.value))
    (row,) = (await client.get(api("/executor/problems"))).json()
    assert (row["target_name"], row["order_number"], row["booking_id"], row["is_vm"]) == ("A10", None, None, False)
    assert row["department"]["name"] == "Product Eco Department"


async def test_return_external_sends_computer_to_cleaning_and_creates_return_task(client, api, login, env, session, sd):  # noqa: F811
    login(env.emp)
    cid = await computer_id(session, "A10")
    r = await client.post(api(f"/bookings/external/{cid}/return"), json={"comment": "Не нужен"})
    assert r.status_code == 200, r.text
    assert (r.json()["status"], r.json()["computer"]["name"], r.json()["return_comment"]) == ("returned", "A10", "Не нужен")

    session.expire_all()
    comp = await session.get(Computer, cid)
    assert (comp.status, comp.department_id, comp.usage_until, comp.writeback_pending) == (ComputerStatus.cleaning, None, None, False)
    booking = (await session.scalars(select(Booking).where(Booking.computer_id == cid))).one()
    assert booking.status == BookingStatus.returned and "вне портала" in booking.purpose and booking.department_id == env.eco.id
    (req,) = (await session.scalars(select(ServiceRequest).where(ServiceRequest.kind == "return"))).all()
    assert req.booking_id == booking.id and "A10" in req.summary
    assert [x["computer"]["id"] for x in (await client.get(api("/bookings/external"))).json()] == [await computer_id(session, "A9")]


async def test_returned_external_computer_waits_for_executor_cleaning(client, api, login, env, session, sd, make_user):  # noqa: F811
    login(env.emp)
    cid = await computer_id(session, "A10")
    await client.post(api(f"/bookings/external/{cid}/return"), json={})
    login(await make_user("worker", role=UserRole.executor.value))
    assert [o["computer"]["name"] for o in (await client.get(api("/executor/returns"))).json()] == ["A10"]
    assert (await client.post(api(f"/executor/returns/{(await client.get(api('/executor/returns'))).json()[0]['id']}/cleaned"))).status_code == 200
    session.expire_all()
    assert (await session.get(Computer, cid)).status != ComputerStatus.cleaning  # дальше — как у любого вернувшегося ПК


@pytest.mark.parametrize("who, name, code", [("other", "A10", 403), ("nodept", "A10", 403), ("emp", "A30", 409), ("emp", "A40", 409),
                                             ("emp", "vm-1", 404), ("emp", "A50", 404)])
async def test_return_external_access_and_state_checks(client, api, login, env, session, sd, who, name, code):  # noqa: F811
    login(getattr(env, who))
    r = await client.post(api(f"/bookings/external/{await computer_id(session, name)}/return"), json={})
    assert r.status_code == code
    assert (await client.post(api("/bookings/external/999999/return"), json={})).status_code == 404


async def test_return_external_twice_is_conflict(client, api, login, env, session, sd):  # noqa: F811
    login(env.emp)
    cid = await computer_id(session, "A10")
    assert (await client.post(api(f"/bookings/external/{cid}/return"), json={})).status_code == 200
    assert (await client.post(api(f"/bookings/external/{cid}/return"), json={})).status_code in (403, 409)


async def test_view_mode_blocks_return_of_external_computer(client, api, login, env, session, make_user):
    admin = await make_user("boss", role=UserRole.admin.value)
    login(admin)
    await client.post(api("/auth/view-as"), json={"user_id": env.emp.id})
    r = await client.post(api(f"/bookings/external/{await computer_id(session, 'A10')}/return"), json={})
    assert r.status_code == 403 and "Режим просмотра" in r.json()["detail"]
