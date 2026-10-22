"""Раздел «Исполнитель» (services/executor.py, api/routes/executor.py): очередь выданных ПК и данные для подключения.

Доступ по ролям проверяет test_api_access.py — здесь поведение под исполнителем.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.config import settings
from app.models import (
    AssetEvent,
    BookingStatus,
    Computer,
    ComputerStatus,
    Department,
    EventType,
    Notification,
    NotificationKind,
    ServiceRequest,
    UserRole,
)
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

    # заявка «Диагностика комплекта» создана в фоне, к заказу и команде заказчика не привязана
    (type_id, summary, description, _), = sd.created
    assert (type_id, summary) == (1252, "HMS Rent: диагностика комплекта A001")
    assert "Не включается, пищит БП" in description and "ТО" in description
    (req,) = await session.scalars(select(ServiceRequest))
    assert (req.kind, req.booking_id, req.department_id, req.user_id) == ("diagnose", None, None, env.worker.id)


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
