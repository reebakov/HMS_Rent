"""Раздел «Исполнитель» (services/executor.py, api/routes/executor.py): очередь выданных ПК и данные для подключения.

Доступ по ролям проверяет test_api_access.py — здесь поведение под исполнителем.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.config import settings
from app.integrations import servicedesk as real_sd
from app.models import (
    AssetEvent,
    Booking,
    BookingStatus,
    Computer,
    ComputerStatus,
    Department,
    EventType,
    Notification,
    NotificationKind,
    ServiceRequest,
    UserRole,
    VirtualMachine,
)
from app.schemas.booking import ExecutorReplace
from app.services import cleaning, executor, runtime

from .sync_fakes import add_booking
from .test_service_requests import boom, sd  # noqa: F401 — sd: фикстура «Service Desk подключён, вызовы записываются»

RESULT = {"host": "A001.ff.local", "ip": "10.1.2.3", "method": "RDP"}


@pytest_asyncio.fixture
async def env(session, make_department, make_user, make_pool, make_computer, login):
    """Исполнитель вошёл; у заказчика две активные брони (ранняя и поздняя) и одна возвращённая."""
    qa = await make_department("QA")
    owner = await make_user("owner", department=qa, display_name="Иван Иванов")
    worker = await make_user("worker", role=UserRole.executor.value, display_name="Пётр Исполнитель")
    pool = await make_pool()
    now = datetime.now(timezone.utc)
    early = await add_booking(session, await make_computer("A001", pool, insight_status="Свободен"), owner, qa, booked_at=now - timedelta(days=2))
    late = await add_booking(session, await make_computer("A002", pool, insight_status="Свободен"), owner, qa, booked_at=now - timedelta(days=1))
    closed = await add_booking(session, await make_computer("A003", pool, insight_status="Свободен"), owner, qa, status="returned")
    login(worker)
    return SimpleNamespace(owner=owner, worker=worker, early=early, late=late, closed=closed)


async def _count(session, model, *where) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*where))


# ---------- очередь ----------

async def test_queue_lists_active_orders_waiting_first(client, api, env):
    await client.post(api(f"/executor/orders/{env.early.id}/result"), json=RESULT)
    rows = (await client.get(api("/executor/orders"))).json()
    # возвращённая бронь в очередь не попадает; подготовленная уходит вниз, хотя она раньше
    assert [r["id"] for r in rows] == [env.late.id, env.early.id]
    assert rows[0]["prepared_at"] is None and rows[1]["prepared_by"]["display_name"] == "Пётр Исполнитель"


async def test_order_page_shows_closed_order_and_404(client, api, env):
    assert (await client.get(api(f"/executor/orders/{env.closed.id}"))).json()["status"] == "returned"
    assert (await client.get(api("/executor/orders/999999"))).status_code == 404


@pytest.mark.parametrize("raw, expected", [
    ("10.1.2.3", "10.1.2.3"), ("  10.1.2.3 ", "10.1.2.3"),
    (None, None), ("", None), ("не назначен", None), ("10.1.2.3, 10.1.2.4", None), ("10.1.2", None), ("fe80::1", None),
])
async def test_order_suggests_ip_from_insight_only_when_valid(client, api, env, session, raw, expected):
    """IP из Insight — подсказка для формы: берётся один корректный IPv4, остальное исполнитель вводит сам."""
    comp = await session.get(Computer, env.early.computer_id)
    comp.ip_address = raw
    await session.commit()
    assert (await client.get(api(f"/executor/orders/{env.early.id}"))).json()["insight_ip"] == expected
    rows = {r["id"]: r for r in (await client.get(api("/executor/orders"))).json()}
    assert rows[env.early.id]["insight_ip"] == expected


# ---------- проблемы по заказам ----------

async def _vm(session, env):
    vm = VirtualMachine(name="A1007", cpu=4, ram_gb=8, disk_gb=100, os_label="Ubuntu 22.04", status="ready",
                        order_number=555, user_id=env.owner.id, department_id=env.early.department_id,
                        requester_name="Иван Иванов", requester_nick="ivan", attrs={})
    session.add(vm)
    await session.commit()
    return vm


def _problem(env, **kw) -> ServiceRequest:
    kw.setdefault("description", "Не включается\n\n---\nКомпьютер: A001 (ITAM-1)\nЗаказ №1")
    return ServiceRequest(kind="problem", user_id=env.owner.id, summary="s", **kw)


async def test_problems_list_open_first_with_target_and_jira_link(client, api, env, session, monkeypatch):
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    vm = await _vm(session, env)
    now = datetime.now(timezone.utc)
    session.add_all([
        _problem(env, booking_id=env.early.id, issue_key="DR-1", status="Done", status_category="done",
                 created_at=now - timedelta(hours=3)),
        _problem(env, booking_id=env.late.id, issue_key="DR-2", status="In Progress", status_category="indeterminate",
                 created_at=now - timedelta(hours=2), description="Шумит кулер\n\n---\nКомпьютер: A002"),
        _problem(env, vm_id=vm.id, issue_key="DR-3", status="Backlog", status_category="new",
                 created_at=now - timedelta(hours=1)),
        _problem(env, booking_id=env.early.id, issue_key=None, error="Service Desk недоступен", created_at=now),
        ServiceRequest(kind="return", user_id=env.owner.id, booking_id=env.early.id, summary="r", description="d",
                       issue_key="DR-9"),  # не проблема — в список не попадает
    ])
    await session.commit()
    rows = (await client.get(api("/executor/problems"))).json()
    # открытые выше (без категории тоже открыта), внутри — свежие выше; закрытая — в конце
    assert [r["issue_key"] for r in rows] == [None, "DR-3", "DR-2", "DR-1"]
    failed, on_vm, on_pc, closed = rows
    assert (failed["error"], failed["issue_url"], failed["message"]) == ("Service Desk недоступен", None, "Не включается")
    assert (on_vm["target_name"], on_vm["is_vm"], on_vm["booking_id"], on_vm["order_number"]) == ("A1007", True, None, 555)
    assert on_pc["message"] == "Шумит кулер"  # данные ПК после «---» исполнитель видит в Jira
    assert (on_pc["target_name"], on_pc["is_vm"], on_pc["booking_id"]) == ("A002", False, env.late.id)
    assert on_pc["issue_url"] == "https://jira.test/browse/DR-2" and on_pc["status"] == "In Progress"
    assert (on_pc["reporter"]["username"], on_pc["department"]["name"]) == ("owner", "QA")
    assert closed["status_category"] == "done" and closed["order_number"] == env.early.order_number


PROBLEM_TRANSITIONS = [
    {"id": "161", "name": "In Progress", "to": {"name": "В работе", "statusCategory": {"key": "indeterminate"}}},
    {"id": "151", "name": "Done", "to": {"name": "Готово", "statusCategory": {"key": "done"}}},
]


async def _open_problem(session, env, **kw) -> ServiceRequest:
    kw.setdefault("issue_key", "DR-5")
    kw.setdefault("status", "Backlog")
    kw.setdefault("status_category", "new")
    req = _problem(env, booking_id=env.early.id, **kw)
    session.add(req)
    await session.commit()
    return req


async def test_problem_transitions_are_listed_from_jira(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    rows = (await client.get(api(f"/executor/problems/{req.id}/transitions"))).json()
    assert rows == [{"id": "161", "name": "In Progress", "to_status": "В работе", "closes": False},
                    {"id": "151", "name": "Done", "to_status": "Готово", "closes": True}]


async def test_problem_moved_to_new_status_without_resolution(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    sd.status = real_sd.SdStatus("In Progress", "indeterminate")  # так Jira ответит после перехода
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "161"})
    assert r.status_code == 200, r.text
    assert sd.moved == [("DR-5", "161", None)]
    assert (r.json()["status"], r.json()["status_category"]) == ("In Progress", "indeterminate")
    await session.refresh(req)
    assert req.status == "In Progress"  # сохранён, список не вернёт старый статус


async def test_problem_closing_transition_sets_resolution_done(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    sd.status = real_sd.SdStatus("Done", "done")
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "151"})
    assert r.status_code == 200 and sd.moved == [("DR-5", "151", "Done")]
    assert r.json()["status_category"] == "done"


async def test_problem_closing_with_comment_answers_customer_publicly(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    sd.status = real_sd.SdStatus("Done", "done")
    r = await client.post(api(f"/executor/problems/{req.id}/transition"),
                          json={"transition_id": "151", "comment": "  Заменили кабель  "})
    assert r.status_code == 200 and sd.moved == [("DR-5", "151", "Done")]
    assert sd.sent == [("DR-5", None, "Заменили кабель")]  # обрезан, без метки портала


@pytest.mark.parametrize("comment", [None, "", "   "])
async def test_problem_transition_without_comment_posts_nothing(client, api, env, session, sd, comment):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "161", "comment": comment})
    assert r.status_code == 200 and sd.sent == [] and sd.moved == [("DR-5", "161", None)]


async def test_problem_comment_failure_keeps_status_unchanged(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available, sd.send_error = PROBLEM_TRANSITIONS, boom()
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "151", "comment": "Готово"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Не удалось отправить комментарий")
    assert sd.moved == []  # повтор не даст дубля комментария и не оставит задачу закрытой без ответа


async def test_problem_comment_too_long_is_422(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "151", "comment": "x" * 2001})
    assert r.status_code == 422


async def test_problem_transition_unknown_or_stale_is_conflict(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "999"})
    assert r.status_code == 409 and "Такого перехода уже нет" in r.json()["detail"] and sd.moved == []


@pytest.mark.parametrize("body", [{}, {"transition_id": ""}, {"transition_id": "x" * 17}], ids=["no_id", "empty", "too_long"])
async def test_problem_transition_validation_422(client, api, env, session, sd, body):  # noqa: F811
    req = await _open_problem(session, env)
    assert (await client.post(api(f"/executor/problems/{req.id}/transition"), json=body)).status_code == 422


async def test_problem_transition_for_missing_other_kind_or_not_created(client, api, env, session, sd):  # noqa: F811
    other = ServiceRequest(kind="return", user_id=env.owner.id, booking_id=env.early.id, summary="s", description="d",
                           issue_key="DR-9")
    failed = _problem(env, booking_id=env.early.id, issue_key=None, error="Service Desk недоступен")
    session.add_all([other, failed])
    await session.commit()
    body = {"transition_id": "161"}
    assert (await client.post(api("/executor/problems/999999/transition"), json=body)).status_code == 404
    assert (await client.get(api(f"/executor/problems/{other.id}/transitions"))).status_code == 404
    assert (await client.post(api(f"/executor/problems/{failed.id}/transition"), json=body)).status_code == 409


async def test_problem_transition_jira_failures_are_clear_errors(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.transitions_error = boom()
    r = await client.get(api(f"/executor/problems/{req.id}/transitions"))
    assert r.status_code == 400 and r.json()["detail"].startswith("Не удалось получить переходы")

    sd.transitions_error, sd.available, sd.move_error = None, PROBLEM_TRANSITIONS, boom()
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "161"})
    assert r.status_code == 400 and r.json()["detail"].startswith("Не удалось сменить статус")
    assert "boom" not in r.json()["detail"] and "Service Desk 500" not in r.json()["detail"]  # подробностей Jira нет


async def test_problem_moved_even_if_status_cannot_be_read_back(client, api, env, session, sd):  # noqa: F811
    req = await _open_problem(session, env)
    sd.available = PROBLEM_TRANSITIONS
    sd.status_errors["DR-5"] = boom()
    r = await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "161"})
    assert r.status_code == 200 and sd.moved == [("DR-5", "161", None)]  # новый статус подтянет worker


async def test_customer_cannot_move_problem(client, api, env, session, login):
    req = await _open_problem(session, env)
    login(env.owner)
    assert (await client.post(api(f"/executor/problems/{req.id}/transition"), json={"transition_id": "161"})).status_code == 403
    assert (await client.get(api(f"/executor/problems/{req.id}/transitions"))).status_code == 403


async def test_problems_empty(client, api, env):
    assert (await client.get(api("/executor/problems"))).json() == []


async def test_problems_hidden_from_customer(client, api, env, login):
    login(env.owner)
    assert (await client.get(api("/executor/problems"))).status_code == 403


# ---------- результат подготовки ----------

async def test_result_saved_and_customer_sees_connection(client, api, env, login, session):
    r = await client.post(api(f"/executor/orders/{env.early.id}/result"), json=RESULT)
    assert r.status_code == 200
    body = r.json()
    assert (body["connection_host"], body["connection_ip"], body["connection_method"]) == ("A001.ff.local", "10.1.2.3", "RDP")
    assert body["connection_login"] == "user" and body["prepared_by"]["id"] == env.worker.id

    [event] = (await session.scalars(select(AssetEvent).where(AssetEvent.event_type == EventType.prepared))).all()
    assert event.actor_id == env.worker.id and "ПК подготовлен" in event.message and "10.1.2.3" in event.message
    [note] = (await session.scalars(select(Notification).where(Notification.user_id == env.owner.id))).all()
    assert (note.kind, note.title) == (NotificationKind.pc_ready, "ПК A001 готов")
    assert "пароль сообщит исполнитель" in note.body

    client.cookies.clear()
    login(env.owner)
    mine = {b["id"]: b for b in (await client.get(api("/bookings/my"))).json()}
    assert mine[env.early.id]["connection_host"] == "A001.ff.local" and mine[env.early.id]["connection_login"] == "user"
    assert "prepared_by" not in mine[env.early.id]  # имя исполнителя заказчику не показывается
    assert mine[env.late.id]["connection_login"] is None  # не подготовлен — логина ещё нет


async def test_same_result_twice_changes_nothing(client, api, env, session):
    url = api(f"/executor/orders/{env.early.id}/result")
    first = (await client.post(url, json=RESULT)).json()
    second = await client.post(url, json={**RESULT, "host": "  A001.ff.local  "})  # пробелы по краям обрезаются
    assert second.status_code == 200 and second.json()["prepared_at"] == first["prepared_at"]
    assert await _count(session, Notification) == 1
    assert await _count(session, AssetEvent, AssetEvent.event_type == EventType.prepared) == 1


async def test_corrected_result_notifies_change(client, api, env, session):
    url = api(f"/executor/orders/{env.early.id}/result")
    await client.post(url, json=RESULT)
    r = await client.post(url, json={**RESULT, "ip": "10.1.2.4", "method": "VNC"})
    assert (r.json()["connection_ip"], r.json()["connection_method"]) == ("10.1.2.4", "VNC")
    titles = (await session.scalars(select(Notification.title).order_by(Notification.id))).all()
    assert titles == ["ПК A001 готов", "Данные подключения к ПК A001 изменены"]
    messages = (await session.scalars(
        select(AssetEvent.message).where(AssetEvent.event_type == EventType.prepared).order_by(AssetEvent.id)
    )).all()
    assert "данные подключения изменены" in messages[1]


@pytest.mark.parametrize("order, status", [("closed", 409), ("missing", 404)])
async def test_result_for_closed_or_unknown_order(client, api, env, session, order, status):
    booking_id = env.closed.id if order == "closed" else 999999
    assert (await client.post(api(f"/executor/orders/{booking_id}/result"), json=RESULT)).status_code == status
    assert await _count(session, Notification) == 0


@pytest.mark.parametrize("patch", [
    {"host": "   "},
    {"host": "A001 ff local"},
    {"host": "-A001"},
    {"host": "A" * 256},
    {"ip": "10.1.2"},
    {"ip": "10.1.2.300"},
    {"ip": ""},
    {"method": "SSH"},
    {"method": None},
])
async def test_result_validation(client, api, env, session, patch):
    r = await client.post(api(f"/executor/orders/{env.early.id}/result"), json={**RESULT, **patch})
    assert r.status_code == 422
    assert await _count(session, Notification) == 0


# ---------- отклонение заказа ----------

REJECT = {"reason": "Заказчик не ответил", "comment": "Нет ответа 5 рабочих дней"}


async def test_reject_closes_order_frees_pc_and_notifies_customer(client, api, env, login, session):
    r = await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=REJECT)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "cancelled" and body["returned_at"] and body["returned_by"] is None
    assert body["return_comment"] == "Заказчик не ответил: Нет ответа 5 рабочих дней"

    comp = (await session.scalars(select(Computer).where(Computer.name == "A001").execution_options(populate_existing=True))).one()
    assert (comp.status, comp.department_id, comp.order_number, comp.usage_until) == (ComputerStatus.available, None, None, None)
    assert comp.pool_id is not None  # обычное отклонение пул не трогает
    (event,) = await session.scalars(select(AssetEvent).where(AssetEvent.event_type == EventType.rejected))
    assert event.actor_id == env.worker.id and "Заказчик не ответил" in event.message

    # заказ ушёл из очереди; заказчик видит причину в колокольчике и в «Моей аренде», но не исполнителя
    assert [o["id"] for o in (await client.get(api("/executor/orders"))).json()] == [env.late.id]
    login(env.owner)
    first = (await client.get(api("/notifications"))).json()["items"][0]
    assert first["kind"] == "order_rejected"
    assert first["title"] == f"Заказ №{env.early.order_number} на ПК A001 отклонён: Заказчик не ответил"
    assert "Нет ответа 5 рабочих дней" in first["body"]
    mine = {b["id"]: b for b in (await client.get(api("/bookings/my"))).json()}[env.early.id]
    assert mine["status"] == "cancelled" and "prepared_by" not in mine and mine["returned_by"] is None


async def test_faulty_removes_pc_from_pool_and_opens_diagnose_request(client, api, env, session, sd):  # noqa: F811
    r = await client.post(api(f"/executor/orders/{env.early.id}/reject"),
                          json={"reason": "Сервер неисправен", "comment": "Не включается, пищит БП"})
    assert r.status_code == 200 and r.json()["status"] == BookingStatus.cancelled
    comp = (await session.scalars(select(Computer).where(Computer.name == "A001").execution_options(populate_existing=True))).one()
    assert (comp.status, comp.pool_id, comp.department_id) == (ComputerStatus.maintenance, None, None)
    assert comp.faulty is True  # только такой ПК портал пишет в Insight как «ТО»

    # заявка «Диагностика комплекта» создана в фоне, к заказу и команде заказчика не привязана
    (type_id, summary, description, _), = sd.created
    assert (type_id, summary) == (1252, "HMS Rent: диагностика комплекта A001")
    assert "Не включается, пищит БП" in description and "ТО" in description
    (req,) = await session.scalars(select(ServiceRequest))
    assert (req.kind, req.booking_id, req.department_id, req.user_id) == ("diagnose", None, None, env.worker.id)


async def test_diagnose_request_remembers_computer_and_previous_pool(client, api, env, session, sd):  # noqa: F811
    comp = (await session.scalars(select(Computer).where(Computer.name == "A001"))).one()
    pool_id = comp.pool_id
    await client.post(api(f"/executor/orders/{env.early.id}/reject"), json={"reason": "Сервер неисправен", "comment": "Не включается"})
    (req,) = await session.scalars(select(ServiceRequest))
    assert (req.computer_id, req.pool_id, req.issue_key, req.portal_done_at) == (comp.id, pool_id, "HMS-1", None)
    assert "Прежний пул: Main" in req.description and "Вернуть в пул" in req.description
    assert "отклонён" not in req.description.splitlines()[0]  # та же заявка нужна и при замене сервера


async def test_diagnose_request_is_kept_even_without_service_desk(client, api, env, session, monkeypatch):
    """Без Jira задачи нет, но ПК и прежний пул запомнены: вернуть ПК в пул можно кнопкой в портале."""
    monkeypatch.setattr(settings, "sd_token", "")
    await client.post(api(f"/executor/orders/{env.early.id}/reject"), json={"reason": "Сервер неисправен", "comment": "Не включается"})
    (req,) = await session.scalars(select(ServiceRequest))
    assert req.kind == "diagnose" and req.issue_key is None and req.computer_id == env.early.computer_id and req.pool_id


async def test_plain_rejection_creates_no_diagnose_request(client, api, env, sd):  # noqa: F811
    await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=REJECT)
    assert sd.created == []


async def test_diagnose_request_failure_does_not_undo_rejection(client, api, env, session, sd):  # noqa: F811
    sd.create_error = boom()
    r = await client.post(api(f"/executor/orders/{env.early.id}/reject"),
                          json={"reason": "Сервер неисправен", "comment": "x"})
    assert r.status_code == 200
    (req,) = await session.scalars(select(ServiceRequest))
    assert req.issue_key is None and req.error  # ошибка сохранена в заявке, заказ остался отклонённым


@pytest.mark.parametrize("body", [
    {"reason": "Заказчик не ответил"}, {"reason": "Заказчик не ответил", "comment": ""},
    {"reason": "Заказчик не ответил", "comment": "   "}, {"reason": "Не нравится", "comment": "x"},
    {"reason": "Заказчик не ответил", "comment": "x" * 2001},
], ids=["no_comment", "empty", "spaces", "unknown_reason", "too_long"])
async def test_reject_validation_422(client, api, env, body):
    assert (await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=body)).status_code == 422


async def test_reject_closed_missing_and_repeated(client, api, env):
    assert (await client.post(api(f"/executor/orders/{env.closed.id}/reject"), json=REJECT)).status_code == 409
    assert (await client.post(api("/executor/orders/999999/reject"), json=REJECT)).status_code == 404
    assert (await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=REJECT)).status_code == 200
    assert (await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=REJECT)).status_code == 409


async def test_customer_cannot_reject(client, api, env, login):
    login(env.owner)
    assert (await client.post(api(f"/executor/orders/{env.early.id}/reject"), json=REJECT)).status_code == 403


# ---------- замена сервера в заказе ----------

async def _spare(session, make_computer, env, name="A010", **kw) -> Computer:
    """Свободный ПК в том же пуле, что и ПК заказов: кандидат на замену (ПК активных заказов помечаются занятыми)."""
    for booking in (env.early, env.late):
        (await session.get(Computer, booking.computer_id)).status = ComputerStatus.booked.value
    pool_id = (await session.get(Computer, env.early.computer_id)).pool_id
    comp = await make_computer(name, None, insight_status="Свободен", **kw)
    comp.pool_id = pool_id
    await session.commit()
    return comp


def _replace(client, api, booking, comp, comment="Не включается"):
    return client.post(api(f"/executor/orders/{booking.id}/replace"), json={"computer_id": comp.id, "comment": comment})


async def test_replacements_are_free_pcs_of_same_tier_from_visible_pools(client, api, env, session, make_computer, make_pool, make_department):
    spare = await _spare(session, make_computer, env, "A010", cpu="Ryzen", ram_gb=32)
    await _spare(session, make_computer, env, "A011", tier="powerful")  # другая категория
    taken = await _spare(session, make_computer, env, "A012")
    taken.status = ComputerStatus.booked.value  # занят
    archived = await _spare(session, make_computer, env, "A013")
    archived.is_archived = True
    draft = await make_computer("A014", await make_pool("Draft", is_published=False), insight_status="Свободен")
    other_dept = await make_department("Other")
    closed_pool = await make_computer("A015", await make_pool("Closed", departments=[other_dept]), insight_status="Свободен")
    await session.commit()
    assert draft.id and closed_pool.id
    rows = (await client.get(api(f"/executor/orders/{env.early.id}/replacements"))).json()
    # A003 свободен (его бронь закрыта), A002 занят заказом, A001 — сам заменяемый
    assert [r["name"] for r in rows] == ["A003", "A010"]
    assert (rows[1]["cpu"], rows[1]["ram_gb"], rows[1]["pool_name"], rows[1]["tier"]) == ("Ryzen", 32, "Main", spare.tier)


async def test_replace_moves_the_order_to_the_new_pc_and_sends_the_old_to_diagnostics(
        client, api, env, session, make_computer, sd, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    await runtime.update(session, {"insight_writeback": True})
    old_pool = (await _pc(session, "A001")).pool_id
    spare = await _spare(session, make_computer, env)
    before = (env.early.order_number, env.early.expected_return_at, env.early.os_label, env.early.department_id)
    session.add(ServiceRequest(kind="prepare", user_id=env.owner.id, booking_id=env.early.id, summary="HMS Rent: подготовить ПК A001",
                               description="d", issue_key="DR-5", status="Backlog", status_category="new"))
    await session.commit()

    r = await _replace(client, api, env.early, spare)
    assert r.status_code == 200, r.text
    assert (r.json()["computer"]["name"], r.json()["order_number"]) == ("A010", before[0])
    booking = (await session.scalars(select(Booking).where(Booking.id == env.early.id).execution_options(populate_existing=True))).one()
    assert (booking.computer_id, booking.order_number, booking.expected_return_at, booking.os_label, booking.department_id) \
        == (spare.id, *before)
    old, new = await _pc(session, "A001"), await _pc(session, "A010")
    assert (old.status, old.pool_id, old.department_id, old.order_number) == (ComputerStatus.maintenance, None, None, None)
    assert (old.faulty, new.faulty) == (True, False)
    assert (new.status, new.department_id, new.order_number, new.usage_until) == (
        ComputerStatus.booked, booking.department_id, booking.order_number, booking.expected_return_at)
    events = [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.replaced]
    assert {(e.computer_id, e.actor_id) for e in events} == {(old.id, env.worker.id), (new.id, env.worker.id)}
    assert any("A010" in e.message and "Не включается" in e.message for e in events)
    # заявка «Диагностика комплекта» помнит старый ПК и его пул, тема задачи подготовки получила новое имя
    (diag,) = await session.scalars(select(ServiceRequest).where(ServiceRequest.kind == "diagnose"))
    assert (diag.computer_id, diag.pool_id) == (old.id, old_pool) and "заменён на A010" in diag.description
    assert ("DR-5", {"summary": "HMS Rent: подготовить ПК A010 (заказ №" + str(before[0]) + ")"}) in [
        (k, {"summary": f["summary"]}) for k, f in sd.updated]
    (note,) = [n for n in (await session.scalars(select(Notification))).all() if "заменён" in n.title]
    assert (note.user_id, note.kind) == (env.owner.id, NotificationKind.request_status) and "A001" in note.body and "A010" in note.title


async def test_replace_queues_insight_write_for_both_pcs_when_enabled(session, env, make_computer, monkeypatch):
    monkeypatch.setattr(executor, "notify", AsyncMock())
    spare = await _spare(session, make_computer, env)
    await runtime.update(session, {"insight_writeback": True})
    await executor.replace_computer(session, env.worker, env.early.id, ExecutorReplace(computer_id=spare.id, comment="Греется"))
    assert [(await _pc(session, n)).writeback_pending for n in ("A001", "A010")] == [True, True]  # статусы и пулы уйдут в Insight


@pytest.mark.parametrize("case", ["prepared", "closed", "same", "booked", "tier", "pool", "archived"])
async def test_replace_conflicts(client, api, env, session, make_computer, make_pool, make_department, case, sd):  # noqa: F811
    spare = await _spare(session, make_computer, env)
    booking, target = env.early, spare
    if case == "prepared":
        booking.prepared_at = datetime.now(timezone.utc)
    elif case == "closed":
        booking, target = env.closed, spare
    elif case == "same":
        target = await _pc(session, "A001")
    elif case == "booked":
        spare.status = ComputerStatus.booked.value
    elif case == "tier":
        spare.tier = "powerful"
    elif case == "pool":
        spare.pool_id = (await make_pool("Closed", departments=[await make_department("Other")])).id
    elif case == "archived":
        spare.is_archived = True
    await session.commit()
    assert (await _replace(client, api, booking, target)).status_code == 409
    if booking is env.early:
        assert (await _pc(session, "A001")).status == ComputerStatus.booked  # ничего не изменилось


async def test_replace_not_found_validation_and_access(client, api, env, session, make_computer, login, sd):  # noqa: F811
    spare = await _spare(session, make_computer, env)
    assert (await client.post(api("/executor/orders/999999/replace"), json={"computer_id": spare.id, "comment": "x"})).status_code == 404
    assert (await client.post(api(f"/executor/orders/{env.early.id}/replace"), json={"computer_id": 999999, "comment": "x"})).status_code == 404
    for body in ({"computer_id": spare.id}, {"computer_id": spare.id, "comment": ""}, {"computer_id": spare.id, "comment": "x" * 2001}):
        assert (await client.post(api(f"/executor/orders/{env.early.id}/replace"), json=body)).status_code == 422
    login(env.owner)
    assert (await _replace(client, api, env.early, spare)).status_code == 403
    assert (await client.get(api(f"/executor/orders/{env.early.id}/replacements"))).status_code == 403


# ---------- диагностика: вернуть ПК в пул ----------

async def _faulty(client, api, env, session) -> ServiceRequest:
    await client.post(api(f"/executor/orders/{env.early.id}/reject"), json={"reason": "Сервер неисправен", "comment": "Не включается"})
    return (await session.scalars(select(ServiceRequest).where(ServiceRequest.kind == "diagnose",
                                                               ServiceRequest.computer_id.is_not(None)))).one()


async def _pc(session, name="A001") -> Computer:
    return (await session.scalars(select(Computer).where(Computer.name == name).execution_options(populate_existing=True))).one()


async def test_diagnostics_list_and_return_to_pool(client, api, env, session, sd, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    req = await _faulty(client, api, env, session)
    (row,) = (await client.get(api("/executor/diagnostics"))).json()
    assert (row["id"], row["computer"]["name"], row["pool_name"], row["comment"]) == (req.id, "A001", "Main", "Не включается")
    assert (row["issue_key"], row["issue_url"]) == ("HMS-1", "https://jira.test/browse/HMS-1")

    done = await client.post(api(f"/executor/diagnostics/{req.id}/repaired"))
    assert done.status_code == 200 and done.json()["id"] == req.id
    comp = await _pc(session)
    assert (comp.status, comp.pool_id, comp.faulty) == (ComputerStatus.available, req.pool_id, False)
    (event,) = await session.scalars(select(AssetEvent).where(AssetEvent.event_type == EventType.repaired))
    assert event.actor_id == env.worker.id and "возвращён в пул «Main»" in event.message
    assert (event.from_status, event.to_status) == (ComputerStatus.maintenance, ComputerStatus.available)
    await session.refresh(req)
    assert req.portal_done_at is not None
    assert (await client.get(api("/executor/diagnostics"))).json() == []  # из списка ушла


async def test_repair_queues_insight_write_only_when_enabled(session, env, client, api, sd, monkeypatch):  # noqa: F811
    monkeypatch.setattr(executor, "notify", AsyncMock())
    req = await _faulty(client, api, env, session)
    comp = await _pc(session)
    comp.writeback_pending = False
    await session.commit()
    await runtime.update(session, {"insight_writeback": True})
    await executor.repair_computer(session, env.worker, req.id)
    comp = await _pc(session)
    assert (comp.status, comp.writeback_pending) == (ComputerStatus.available, True)  # «Ожидает» и пул уйдут в Insight


async def test_repair_is_idempotent_conflict_and_validated(client, api, env, session, sd):  # noqa: F811
    req = await _faulty(client, api, env, session)
    assert (await client.post(api(f"/executor/diagnostics/{req.id}/repaired"))).status_code == 200
    assert (await client.post(api(f"/executor/diagnostics/{req.id}/repaired"))).status_code == 409
    assert (await client.post(api("/executor/diagnostics/999999/repaired"))).status_code == 404
    other = ServiceRequest(kind="return", user_id=env.owner.id, summary="s", description="d", issue_key="X-1")
    session.add(other)
    await session.commit()
    assert (await client.post(api(f"/executor/diagnostics/{other.id}/repaired"))).status_code == 404  # не диагностика


async def test_repair_when_pool_was_deleted_keeps_pc_out_of_pools(client, api, env, session, sd):  # noqa: F811
    from app.models import Pool
    req = await _faulty(client, api, env, session)
    gone = Pool(name="Удалённый")
    session.add(gone)
    await session.commit()
    req.pool_id = gone.id  # прежний пул ПК удалили после того, как его вывели
    await session.commit()
    await session.delete(gone)
    await session.commit()
    await session.refresh(req)
    assert req.pool_id is None  # FK ON DELETE SET NULL
    (row,) = (await client.get(api("/executor/diagnostics"))).json()
    assert row["pool_name"] is None
    assert (await client.post(api(f"/executor/diagnostics/{req.id}/repaired"))).status_code == 200
    comp = await _pc(session)
    assert (comp.status, comp.pool_id) == (ComputerStatus.available, None)
    (event,) = await session.scalars(select(AssetEvent).where(AssetEvent.event_type == EventType.repaired))
    assert "прежний пул не известен" in event.message


async def test_diagnostics_list_skips_returned_pcs_and_legacy_requests(client, api, env, session, sd):  # noqa: F811
    legacy = ServiceRequest(kind="diagnose", user_id=env.worker.id, summary="s", description="d", issue_key="HMS-50")
    session.add(legacy)  # создана до привязки к ПК: показать нечего
    await session.commit()
    req = await _faulty(client, api, env, session)
    comp = await _pc(session)
    comp.status = ComputerStatus.available  # администратор вернул ПК вручную
    await session.commit()
    assert (await client.get(api("/executor/diagnostics"))).json() == []
    assert req.id != legacy.id


async def test_customer_cannot_see_or_close_diagnostics(client, api, env, session, login, sd):  # noqa: F811
    req = await _faulty(client, api, env, session)
    login(env.owner)
    assert (await client.get(api("/executor/diagnostics"))).status_code == 403
    assert (await client.post(api(f"/executor/diagnostics/{req.id}/repaired"))).status_code == 403


# ---------- ссылка на заявку в Jira ----------

def _request(env, booking, **kw) -> ServiceRequest:
    return ServiceRequest(kind="prepare", user_id=env.owner.id, booking_id=booking.id, summary="s", description="d", **kw)


async def test_orders_link_to_prepare_request_in_jira(client, api, env, session, monkeypatch):
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test/")
    session.add_all([
        _request(env, env.early, issue_key="HMS-77", status="В работе"),
        ServiceRequest(kind="return", user_id=env.owner.id, booking_id=env.early.id, summary="s", description="d",
                       issue_key="HMS-80"),
        _request(env, env.late, issue_key=None, error="Service Desk недоступен"),  # Jira не приняла заявку
    ])
    await session.commit()

    rows = {r["id"]: r for r in (await client.get(api("/executor/orders"))).json()}
    early, late = rows[env.early.id], rows[env.late.id]
    # ссылка — на заявку «подготовить ПК» (не на возврат) и для сотрудника поддержки (browse)
    assert (early["request_key"], early["request_url"], early["request_status"]) == (
        "HMS-77", "https://jira.test/browse/HMS-77", "В работе")
    assert (late["request_key"], late["request_url"], late["request_error"]) == (None, None, "Service Desk недоступен")

    # страница заказа и ответы на действия исполнителя несут ту же ссылку
    page = (await client.get(api(f"/executor/orders/{env.early.id}"))).json()
    assert page["request_url"] == "https://jira.test/browse/HMS-77"
    saved = (await client.post(api(f"/executor/orders/{env.early.id}/result"), json=RESULT)).json()
    assert saved["request_key"] == "HMS-77"


async def test_order_without_request_has_no_link(client, api, env):
    page = (await client.get(api(f"/executor/orders/{env.early.id}"))).json()
    assert (page["request_key"], page["request_url"], page["request_status"], page["request_error"]) == (None,) * 4


# ---------- очистка вернувшихся ПК ----------

async def test_returns_queue_and_confirm_cleaned(client, api, env, session, monkeypatch):
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    # A003 вернули, на нём бронь env.closed; ПК ждёт очистки, у возврата есть заявка Service Desk
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003"))).one()
    comp.status = ComputerStatus.cleaning
    env.closed.returned_at = datetime.now(timezone.utc) - timedelta(hours=2)
    session.add(ServiceRequest(kind="return", user_id=env.owner.id, booking_id=env.closed.id, summary="s", description="d",
                               issue_key="HMS-90", status="Ожидает поддержки"))
    await session.commit()

    (row,) = (await client.get(api("/executor/returns"))).json()
    assert row["id"] == env.closed.id and row["computer"]["name"] == "A003"
    assert (row["request_key"], row["request_url"]) == ("HMS-90", "https://jira.test/browse/HMS-90")  # заявка «Возврат ПК»

    done = await client.post(api(f"/executor/returns/{env.closed.id}/cleaned"))
    assert done.status_code == 200
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003").execution_options(populate_existing=True))).one()
    assert comp.status == ComputerStatus.available
    (event,) = await session.scalars(select(AssetEvent).where(AssetEvent.event_type == EventType.cleaned))
    assert event.actor_id == env.worker.id
    assert (await client.get(api("/executor/returns"))).json() == []


async def test_confirm_cleaned_conflicts_and_access(client, api, env, login, session):
    # ПК A003 свободен (очистка не требуется): подтверждать нечего
    assert (await client.post(api(f"/executor/returns/{env.closed.id}/cleaned"))).status_code == 409
    assert (await client.post(api("/executor/returns/999999/cleaned"))).status_code == 404
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003"))).one()
    comp.status = ComputerStatus.cleaning
    await session.commit()
    login(env.owner)  # заказчик очистку подтвердить не может
    assert (await client.post(api(f"/executor/returns/{env.closed.id}/cleaned"))).status_code == 403
    assert (await client.get(api("/executor/returns"))).status_code == 403
    login(env.worker)
    assert (await client.post(api(f"/executor/returns/{env.closed.id}/cleaned"))).status_code == 200
    assert (await client.post(api(f"/executor/returns/{env.closed.id}/cleaned"))).status_code == 409  # повтор


async def test_confirm_cleaned_queues_insight_write_only_when_enabled(session, env):
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003"))).one()
    comp.status = ComputerStatus.cleaning
    await session.commit()
    await runtime.update(session, {"insight_writeback": True})
    await executor.confirm_cleaned(session, env.worker, env.closed.id)
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003").execution_options(populate_existing=True))).one()
    assert (comp.status, comp.writeback_pending) == (ComputerStatus.available, True)  # «Ожидает» уйдёт в Insight


async def test_waiting_list_keeps_latest_return_per_pc_and_filters_by_age(session, env):
    comp = (await session.scalars(select(Computer).where(Computer.name == "A003"))).one()
    comp.status = ComputerStatus.cleaning
    dept = await session.get(Department, env.closed.department_id)
    first = await add_booking(session, comp, env.owner, dept, status="returned")
    second = await add_booking(session, comp, env.owner, dept, status="returned")
    now = datetime.now(timezone.utc)
    env.closed.returned_at, first.returned_at, second.returned_at = now - timedelta(days=3), now - timedelta(days=2), now - timedelta(hours=30)
    await session.commit()
    rows = await cleaning.list_waiting(session)
    assert [b.id for b in rows] == [second.id]  # последний возврат этого ПК
    assert [b.id for b in await cleaning.list_waiting(session, older_than=timedelta(days=2))] == []
    assert [b.id for b in await cleaning.list_waiting(session, older_than=timedelta(days=1))] == [second.id]


# ---------- нормативы для интерфейса ----------

async def test_norms_endpoint_for_executor_and_closed_for_customer(client, api, env, session, login, sd):  # noqa: F811
    req = ServiceRequest(kind="prepare", user_id=env.owner.id, booking_id=env.early.id, summary="s", description="d",
                         issue_key="DR-9", status="Backlog", status_category="new")
    session.add(req)
    await session.commit()
    rows = (await client.get(api("/executor/norms"))).json()
    assert [(r["issue_key"], r["limit_name"], r["taken"]) for r in rows] == [("DR-9", "1 рабочий день", False)]
    login(env.owner)
    assert (await client.get(api("/executor/norms"))).status_code == 403
