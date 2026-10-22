"""Сквозные сценарии через HTTP API: цепочки действий разных ролей, как их проходит пилот.

Модульные тесты проверяют каждое правило отдельно; здесь — что роли, статусы, уведомления и права работают вместе.
vSphere заменён фейком из test_vm_jobs, фоновые шаги worker'а вызываются напрямую.
"""
from datetime import timedelta
from types import SimpleNamespace

import pytest_asyncio

from app.core import clock
from app.models import UserRole
from app.services import term_limit, vm_jobs
from tests.test_vm_jobs import pauses, vm_on, vsphere  # noqa: F401 — фикстуры: vCenter, фейк vSphere, без пауз

TODAY = clock.today()
MONTH = TODAY + timedelta(days=30)
LIMIT = term_limit.add_months(TODAY, term_limit.MAX_TERM_MONTHS)
FAR = LIMIT + timedelta(days=60)


@pytest_asyncio.fixture
async def world(make_department, make_pool, make_user, make_computer):
    """Команда QA (владелец заказа и коллега), чужой отдел, исполнитель и администратор; один свободный ПК в пуле."""
    qa, ops = await make_department("QA"), await make_department("Ops")
    pool = await make_pool("Main")
    return SimpleNamespace(
        qa=qa,
        owner=await make_user("owner", department=qa, display_name="Иван Иванов"),
        mate=await make_user("mate", department=qa),
        stranger=await make_user("stranger", department=ops),
        executor=await make_user("exec", role=UserRole.executor.value),
        admin=await make_user("boss", role=UserRole.admin.value),
        pc=await make_computer("A001", pool, insight_status="Свободен"),
    )


def book_body(world, until=MONTH):
    return {"computer_id": world.pc.id, "requester_nick": "ivan", "expected_return_at": until.isoformat()}


async def titles(client, api) -> list[str]:
    return [n["title"] for n in (await client.get(api("/notifications"))).json()["items"]]


async def free_pcs(client, api) -> list[str]:
    return [c["name"] for c in (await client.get(api("/computers"))).json()]


async def test_pc_from_booking_to_return(client, login, api, world):
    # заказчик берёт ПК: он исчезает из каталога, заказ идёт на его отдел, имя — из профиля
    login(world.owner)
    assert await free_pcs(client, api) == ["A001"]
    r = await client.post(api("/bookings"), json=book_body(world))
    assert r.status_code == 201, r.text
    booking = r.json()
    assert booking["status"] == "active" and booking["department"]["name"] == "QA"
    assert booking["requester_name"] == "Иван Иванов" and booking["connection_host"] is None
    assert await free_pcs(client, api) == []

    # исполнитель видит заказ в очереди ждущим подготовки и вносит данные подключения
    login(world.executor)
    (order,) = (await client.get(api("/executor/orders"))).json()
    assert order["id"] == booking["id"] and order["prepared_at"] is None
    done = await client.post(api(f"/executor/orders/{booking['id']}/result"),
                             json={"host": "A001.ff.local", "ip": "10.1.2.3", "method": "RDP"})
    assert done.status_code == 200 and done.json()["prepared_by"]["username"] == "exec"

    # заказчик получает уведомление и видит данные; имя исполнителя ему не показывается
    login(world.owner)
    assert await titles(client, api) == ["ПК A001 готов"]
    (mine,) = (await client.get(api("/bookings/my"))).json()
    assert (mine["connection_host"], mine["connection_ip"], mine["connection_login"], mine["connection_method"]) == (
        "A001.ff.local", "10.1.2.3", "user", "RDP")
    assert "prepared_by" not in mine

    # коллега по команде видит заказ и продлевает; чужой отдел не может ни продлить, ни вернуть
    login(world.mate)
    assert [b["id"] for b in (await client.get(api("/bookings/my"))).json()] == [booking["id"]]
    later = MONTH + timedelta(days=10)
    ext = await client.post(api(f"/bookings/{booking['id']}/extend"), json={"expected_return_at": later.isoformat()})
    assert ext.status_code == 200 and ext.json()["expected_return_at"] == later.isoformat()
    login(world.stranger)
    assert (await client.get(api("/bookings/my"))).json() == []
    for action, body in (("extend", {"expected_return_at": (later + timedelta(days=1)).isoformat()}), ("return", {})):
        assert (await client.post(api(f"/bookings/{booking['id']}/{action}"), json=body)).status_code == 403

    # коллега возвращает ПК: заказ закрыт, в очереди исполнителя его нет, данные подключения изменить нельзя, ПК свободен
    login(world.mate)
    back = await client.post(api(f"/bookings/{booking['id']}/return"), json={"comment": "всё работает"})
    assert back.status_code == 200 and back.json()["status"] == "returned"
    login(world.executor)
    assert (await client.get(api("/executor/orders"))).json() == []
    late = await client.post(api(f"/executor/orders/{booking['id']}/result"),
                             json={"host": "A001.ff.local", "ip": "10.1.2.4", "method": "RDP"})
    assert late.status_code == 409
    login(world.stranger)
    assert await free_pcs(client, api) == ["A001"]


async def test_second_person_cannot_take_the_same_pc(client, login, api, world, make_user):
    login(world.owner)
    assert (await client.post(api("/bookings"), json=book_body(world))).status_code == 201
    other = await make_user("other", department=world.qa)
    login(other)
    assert (await client.post(api("/bookings"), json=book_body(world))).status_code == 409


async def test_executor_correction_notifies_customer_again(client, login, api, world):
    login(world.owner)
    booking = (await client.post(api("/bookings"), json=book_body(world))).json()
    login(world.executor)
    url = api(f"/executor/orders/{booking['id']}/result")
    first = {"host": "A001.ff.local", "ip": "10.1.2.3", "method": "RDP"}
    assert (await client.post(url, json=first)).status_code == 200
    assert (await client.post(url, json=first)).status_code == 200  # повтор тех же данных ничего не меняет
    assert (await client.post(url, json=first | {"ip": "10.1.2.9"})).status_code == 200
    login(world.owner)
    assert await titles(client, api) == ["Данные подключения к ПК A001 изменены", "ПК A001 готов"]
    assert (await client.get(api("/notifications"))).json()["unread"] == 2


async def test_term_beyond_limit_goes_through_admin_decision(client, login, api, world):
    login(world.owner)
    booking = (await client.post(api("/bookings"), json=book_body(world, until=FAR))).json()
    # заказ оформлен на максимум, на нужный срок создана заявка администратору
    assert booking["expected_return_at"] == LIMIT.isoformat() and booking["requested_return_at"] == FAR.isoformat()

    login(world.admin)
    (req,) = (await client.get(api("/admin/term-requests"))).json()
    approved = await client.post(api(f"/admin/term-requests/{req['id']}/approve"), json={})
    assert approved.status_code == 200
    assert (await client.get(api("/admin/term-requests"))).json() == []
    assert (await client.post(api(f"/admin/term-requests/{req['id']}/approve"), json={})).status_code == 409  # повтор

    login(world.owner)
    (mine,) = (await client.get(api("/bookings/my"))).json()
    assert mine["expected_return_at"] == FAR.isoformat() and mine["requested_return_at"] is None
    assert (await titles(client, api))[0].startswith("Срок ПК A001 согласован до")


async def test_term_request_rejection_keeps_maximum(client, login, api, world):
    login(world.owner)
    await client.post(api("/bookings"), json=book_body(world, until=FAR))
    login(world.admin)
    (req,) = (await client.get(api("/admin/term-requests"))).json()
    assert (await client.post(api(f"/admin/term-requests/{req['id']}/reject"))).status_code == 200
    login(world.owner)
    (mine,) = (await client.get(api("/bookings/my"))).json()
    assert mine["expected_return_at"] == LIMIT.isoformat()
    assert (await titles(client, api))[0].endswith("не согласован")


async def test_roles_do_not_leak(client, login, api, world):
    login(world.owner)
    assert (await client.get(api("/executor/orders"))).status_code == 403  # сотрудник — не исполнитель
    assert (await client.get(api("/admin/stats"))).status_code == 403
    login(world.executor)
    assert (await client.get(api("/admin/stats"))).status_code == 403  # исполнитель — не администратор
    assert (await client.get(api("/executor/orders"))).status_code == 200
    login(world.admin)
    assert (await client.get(api("/executor/orders"))).status_code == 200  # администратору раздел доступен


async def test_vm_from_order_to_deletion(session, client, login, api, world, vm_on, vsphere, pauses):  # noqa: F811
    login(world.owner)
    body = {"cpu": 2, "ram_gb": 4, "disk_gb": 50, "requester_nick": "ivan", "expected_return_at": MONTH.isoformat()}
    created = await client.post(api("/vms"), json=body)
    assert created.status_code == 201, created.text
    vm = created.json()
    assert vm["status"] == "queued" and vm["name"].startswith("A1") and vm["requester_name"] == "Иван Иванов"

    # worker создаёт ВМ: заказчик видит IP и способ подключения и получает уведомление
    assert await vm_jobs.create_next(session) is True
    (mine,) = (await client.get(api("/vms/my"))).json()
    assert (mine["status"], mine["ip_address"], mine["connection_login"]) == ("ready", "10.0.0.5", "user")
    assert await titles(client, api) == [f"ВМ {vm['name']} готова"]

    # коллега продлевает; чужой отдел не может ни продлить, ни удалить
    login(world.mate)
    later = MONTH + timedelta(days=10)
    ext = await client.post(api(f"/vms/{vm['id']}/extend"), json={"expected_return_at": later.isoformat()})
    assert ext.status_code == 200 and ext.json()["expected_return_at"] == later.isoformat()
    login(world.stranger)
    assert (await client.post(api(f"/vms/{vm['id']}/release"))).status_code == 403
    assert (await client.post(api(f"/vms/{vm['id']}/extend"),
                              json={"expected_return_at": (later + timedelta(days=1)).isoformat()})).status_code == 403

    # коллега удаляет, worker снимает ВМ в vCenter по moid
    login(world.mate)
    gone = await client.post(api(f"/vms/{vm['id']}/release"))
    assert gone.status_code == 200 and gone.json()["status"] == "deleting"
    assert (await client.post(api(f"/vms/{vm['id']}/release"))).status_code == 409  # повтор
    assert await vm_jobs.delete_next(session) is True
    assert vsphere.deleted == ["vm-1"]
    (after,) = (await client.get(api("/vms/my"))).json()
    assert after["id"] == vm["id"] and after["status"] == "deleted"
