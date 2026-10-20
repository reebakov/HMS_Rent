"""Админка: детали запуска синхронизации (GET /admin/sync/runs/{id}), просрочки (GET /admin/overdue)
и продления (GET /admin/extensions, POST /admin/extensions/{id}/ack)."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import clock as app_clock
from app.models import BookingExtension, SyncRun, UserRole
from tests.sync_fakes import add_booking
from tests.test_overdue import add_vm

TODAY = date(2026, 6, 15)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(app_clock, "today", lambda: TODAY)


@pytest.fixture
async def admin(make_user, login):
    return login(await make_user("boss", role=UserRole.admin.value))


async def add_run(session, **kw) -> SyncRun:
    run = SyncRun(mode="mock", status="success", **kw)
    session.add(run)
    await session.commit()
    return run


# ---------- доступ ----------

@pytest.mark.parametrize("path", ["/admin/sync/runs/1", "/admin/overdue", "/admin/extensions"])
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


# ---------- продления ----------

async def add_extension(session, booking, user, *, created_at: datetime | None = None, acknowledged_by=None,
                        **kw) -> BookingExtension:
    ext = BookingExtension(booking_id=booking.id, user_id=user.id, old_return_at=TODAY, new_return_at=TODAY + timedelta(days=7),
                           acknowledged_by_id=acknowledged_by.id if acknowledged_by else None,
                           acknowledged_at=datetime.now(timezone.utc) if acknowledged_by else None,
                           **({"created_at": created_at} if created_at else {}), **kw)
    session.add(ext)
    await session.commit()
    return ext


@pytest.fixture
async def rented(session, make_user, make_department, make_computer):
    dept = await make_department("QA")
    user = await make_user("ivanov", department=dept, display_name="Иван Иванов")
    return user, await add_booking(session, await make_computer("PC-1"), user, dept)


async def test_extensions_fields(admin, api, session, rented):
    user, booking = rented
    ext = await add_extension(session, booking, user, comment="ещё неделя")
    (item,) = (await admin.get(api("/admin/extensions"))).json()
    assert (item["id"], item["user"]["display_name"], item["comment"]) == (ext.id, "Иван Иванов", "ещё неделя")
    assert (item["old_return_at"], item["new_return_at"]) == ("2026-06-15", "2026-06-22")
    assert item["booking"]["computer"]["name"] == "PC-1" and item["booking"]["department"]["name"] == "QA"
    assert (item["kind"], item["name"], item["vm"]) == ("pc", "PC-1", None)
    assert item["acknowledged_at"] is None and item["acknowledged_by"] is None and item["created_at"]


def _dept(booking):
    """Отдел брони для фабрик (department из bookings лениво не подгружается в async)."""
    return SimpleNamespace(id=booking.department_id)


async def add_vm_extension(session, vm, user, **kw) -> BookingExtension:
    ext = BookingExtension(vm_id=vm.id, user_id=user.id, old_return_at=TODAY, new_return_at=TODAY + timedelta(days=7), **kw)
    session.add(ext)
    await session.commit()
    return ext


async def test_extensions_list_both_kinds(admin, api, session, rented):
    """Журнал общий для ПК и ВМ: kind различает вид, у ПК заполнен booking, у ВМ — vm."""
    user, booking = rented
    vm = await add_vm(session, user, _dept(booking), name="rent-box", expected_return_at=TODAY + timedelta(days=7))
    pc_ext = await add_extension(session, booking, user, created_at=datetime.now(timezone.utc) - timedelta(hours=1))
    vm_ext = await add_vm_extension(session, vm, user, comment="ещё сборка")

    items = {i["id"]: i for i in (await admin.get(api("/admin/extensions"))).json()}
    assert list(items) == [vm_ext.id, pc_ext.id]  # свежие сверху независимо от вида
    v = items[vm_ext.id]
    assert (v["kind"], v["name"], v["booking"], v["comment"]) == ("vm", "rent-box", None, "ещё сборка")
    assert (v["vm"]["id"], v["vm"]["order_number"], v["vm"]["department"]["name"], v["vm"]["status"]) == (
        vm.id, vm.order_number, "QA", "ready")
    assert (v["old_return_at"], v["new_return_at"], v["user"]["display_name"]) == ("2026-06-15", "2026-06-22", "Иван Иванов")
    assert (items[pc_ext.id]["kind"], items[pc_ext.id]["name"]) == ("pc", "PC-1")


async def test_extension_ack_vm(admin, api, session, rented):
    user, booking = rented
    vm = await add_vm(session, user, _dept(booking))
    ext = await add_vm_extension(session, vm, user)
    r = await admin.post(api(f"/admin/extensions/{ext.id}/ack"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["kind"], body["vm"]["id"], body["booking"]) == ("vm", vm.id, None)
    assert body["acknowledged_at"] and body["acknowledged_by"]["username"] == "boss"
    again = (await admin.post(api(f"/admin/extensions/{ext.id}/ack"))).json()  # повтор ничего не меняет
    assert again["acknowledged_at"] == body["acknowledged_at"]


async def test_vm_extension_by_teammate_then_admin_sees_it_new_and_vm_not_overdue(admin, login, api, session, make_user,
                                                                                  rented):
    """Сквозной путь: ВМ просрочена, команда продлила → просрочка ушла, продление ждёт «Принято», потом принято."""
    user, booking = rented
    vm = await add_vm(session, user, _dept(booking), name="rent-late", expected_return_at=TODAY - timedelta(days=3))
    assert [(i["name"], i["days"]) for i in (await admin.get(api("/admin/overdue"))).json()] == [("rent-late", 3)]

    mate = await make_user("mate", department=_dept(booking))
    new = (TODAY + timedelta(days=10)).isoformat()
    assert (await login(mate).post(api(f"/vms/{vm.id}/extend"), json={"expected_return_at": new})).status_code == 200

    login(await make_user("boss2", role=UserRole.admin.value))
    assert (await admin.get(api("/admin/overdue"))).json() == []
    (ext,) = (await admin.get(api("/admin/extensions"))).json()
    assert (ext["kind"], ext["name"], ext["acknowledged_at"], ext["new_return_at"]) == ("vm", "rent-late", None, new)
    assert ext["user"]["username"] == "mate" and ext["vm"]["expected_return_at"] == new
    assert (await admin.post(api(f"/admin/extensions/{ext['id']}/ack"))).json()["acknowledged_by"]["username"] == "boss2"


async def test_extensions_new_first_then_recent_acknowledged(admin, api, session, rented, make_user):
    user, booking = rented
    boss = await make_user("other-admin", role=UserRole.admin.value)
    now = datetime.now(timezone.utc)
    seen = await add_extension(session, booking, user, acknowledged_by=boss, created_at=now - timedelta(hours=1))
    old_new = await add_extension(session, booking, user, created_at=now - timedelta(days=30))  # непринятое — всегда видно
    fresh_new = await add_extension(session, booking, user, created_at=now - timedelta(hours=2))
    await add_extension(session, booking, user, acknowledged_by=boss, created_at=now - timedelta(days=15))  # уже старое
    ids = [i["id"] for i in (await admin.get(api("/admin/extensions"))).json()]
    assert ids == [fresh_new.id, old_new.id, seen.id]


async def test_extension_ack(admin, api, session, rented):
    user, booking = rented
    ext = await add_extension(session, booking, user)
    r = await admin.post(api(f"/admin/extensions/{ext.id}/ack"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acknowledged_at"] and body["acknowledged_by"]["username"] == "boss"
    again = (await admin.post(api(f"/admin/extensions/{ext.id}/ack"))).json()  # повтор ничего не меняет
    assert datetime.fromisoformat(again["acknowledged_at"]) == datetime.fromisoformat(body["acknowledged_at"])


async def test_extension_ack_not_found(admin, api):
    resp = await admin.post(api("/admin/extensions/999/ack"))
    assert resp.status_code == 404 and resp.json()["detail"] == "Продление не найдено"
