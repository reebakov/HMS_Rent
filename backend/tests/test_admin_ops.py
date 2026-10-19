"""Админка: детали запуска синхронизации (GET /admin/sync/runs/{id}) и просрочки (GET /admin/overdue)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import SyncRun, UserRole
from app.services import overdue
from tests.sync_fakes import add_booking
from tests.test_overdue import add_vm

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(overdue, "_today", lambda: TODAY)


@pytest.fixture
async def admin(make_user, login):
    return login(await make_user("boss", role=UserRole.admin.value))


async def add_run(session, **kw) -> SyncRun:
    run = SyncRun(mode="mock", status="success", **kw)
    session.add(run)
    await session.commit()
    return run


# ---------- доступ ----------

@pytest.mark.parametrize("path", ["/admin/sync/runs/1", "/admin/overdue"])
async def test_admin_ops_requires_login_and_admin_role(client, login, make_user, api, session, path):
    await add_run(session)
    assert (await client.get(api(path))).status_code == 401
    login(await make_user("emp"))
    assert (await client.get(api(path))).status_code == 403


# ---------- детали запуска ----------

async def test_sync_run_not_found(admin, api):
    resp = await admin.get(api("/admin/sync/runs/999"))
    assert resp.status_code == 404 and resp.json()["detail"] == "Запуск не найден"


async def test_sync_run_details(admin, api, session):
    details = {
        "updated": [{"id": 1, "name": "A001", "changes": [{"field": "ОЗУ, ГБ", "old": "8", "new": "16"}]}],
        "created": [{"id": 2, "name": "A002"}, {"id": 3, "name": "A003"}],
        "archived": [{"id": 4, "name": "A004"}],
    }
    run = await add_run(session, total=5, details=details)
    body = (await admin.get(api(f"/admin/sync/runs/{run.id}"))).json()
    assert body["id"] == run.id and body["started_at"]
    assert {k: body[k] for k in ("updated", "created", "archived")} == details


@pytest.mark.parametrize("details", [{}, {"updated": []}])
async def test_sync_run_empty_details_give_empty_lists(admin, api, session, details):
    run = await add_run(session, details=details)  # старые запуски (до появления деталей) — пустой JSON
    body = (await admin.get(api(f"/admin/sync/runs/{run.id}"))).json()
    assert (body["updated"], body["created"], body["archived"]) == ([], [], [])


# ---------- просрочки ----------

async def test_overdue_empty(admin, api):
    resp = await admin.get(api("/admin/overdue"))
    assert resp.status_code == 200 and resp.json() == []


async def test_overdue_fields_and_kinds(admin, api, session, make_user, make_department, make_computer):
    dept = await make_department("QA")
    user = await make_user("ivanov", department=dept, email="ivanov@corp.test")
    b = await add_booking(session, await make_computer("PC-1"), user, dept, expected_return_at=TODAY - timedelta(days=3),
                          requester_name="Иван Иванов", requester_nick="ivan")
    ready_at = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
    vm = await add_vm(session, user, dept, name="vm-1", expected_return_at=TODAY - timedelta(days=4), ready_at=ready_at)

    items = {i["kind"]: i for i in (await admin.get(api("/admin/overdue"))).json()}
    assert set(items) == {"pc", "vm"}
    pc = items["pc"]
    assert (pc["id"], pc["order_number"], pc["name"], pc["department"]) == (b.id, b.order_number, "PC-1", "QA")
    assert (pc["requester_name"], pc["requester_nick"], pc["email"]) == ("Иван Иванов", "ivan", "ivanov@corp.test")
    assert (pc["due"], pc["days"]) == ("2026-06-12", 3) and pc["taken_at"]
    v = items["vm"]
    assert (v["id"], v["order_number"], v["name"], v["email"]) == (vm.id, vm.order_number, "vm-1", "ivanov@corp.test")
    assert (v["requester_name"], v["requester_nick"], v["department"]) == ("Пётр Петров", "petr", "QA")
    assert (v["due"], v["days"]) == ("2026-06-11", 4)
    assert datetime.fromisoformat(v["taken_at"]) == ready_at  # у ВМ «взята» — когда стала готова


async def test_overdue_vm_taken_at_falls_back_to_created_at(admin, api, session, make_user, make_department):
    dept = await make_department("QA")
    await add_vm(session, await make_user("ivanov", department=dept), dept, status="failed")  # ready_at нет
    (item,) = (await admin.get(api("/admin/overdue"))).json()
    assert item["taken_at"] and item["email"] is None  # email не задан у пользователя


async def test_overdue_sorted_by_days_desc_across_kinds(admin, api, session, make_user, make_department, make_computer):
    dept = await make_department("QA")
    user = await make_user("ivanov", department=dept)
    for name, days in (("PC-2", 2), ("PC-9", 9)):
        await add_booking(session, await make_computer(name), user, dept, expected_return_at=TODAY - timedelta(days=days))
    for name, days in (("vm-5", 5), ("vm-1", 1)):
        await add_vm(session, user, dept, name=name, expected_return_at=TODAY - timedelta(days=days))
    items = (await admin.get(api("/admin/overdue"))).json()
    assert [(i["name"], i["days"]) for i in items] == [("PC-9", 9), ("vm-5", 5), ("PC-2", 2), ("vm-1", 1)]


async def test_overdue_admin_sees_all_users_and_departments(admin, api, session, make_user, make_department,
                                                            make_computer):
    due = TODAY - timedelta(days=1)
    for n in ("a", "b"):
        dept = await make_department(f"Dept-{n}")
        user = await make_user(f"user-{n}", department=dept)
        await add_booking(session, await make_computer(f"PC-{n}"), user, dept, expected_return_at=due)
        await add_vm(session, user, dept, name=f"vm-{n}", expected_return_at=due)
    items = (await admin.get(api("/admin/overdue"))).json()
    assert {(i["kind"], i["department"]) for i in items} == {
        ("pc", "Dept-a"), ("pc", "Dept-b"), ("vm", "Dept-a"), ("vm", "Dept-b")}


async def test_overdue_skips_not_overdue(admin, api, session, make_user, make_department, make_computer):
    dept = await make_department("QA")
    user = await make_user("ivanov", department=dept)
    await add_booking(session, await make_computer(), user, dept, expected_return_at=TODAY)
    await add_vm(session, user, dept, status="deleted")
    assert (await admin.get(api("/admin/overdue"))).json() == []
