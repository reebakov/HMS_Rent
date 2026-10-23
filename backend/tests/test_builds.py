"""Сборка по запросу в портале (services/builds.py): выдача собранного ПК, отклонение, отмена заказчиком, закрытие в Jira.

Окружение — из test_executor (исполнитель вошёл, заказчик в отделе QA), Jira — FakeSd из test_service_requests.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import null, select

from app.core import clock
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import (
    AssetEvent,
    Booking,
    Computer,
    ComputerStatus,
    Department,
    EventType,
    Notification,
    NotificationKind,
    ServiceRequest,
    TermRequest,
)
from app.services import builds, jira_closure, service_requests

from .test_executor import env  # noqa: F401 — фикстура: исполнитель, заказчик, активные брони
from .test_service_requests import sd  # noqa: F401 — Service Desk подключён, клиент Jira подменён

FORM = {"host": "A500.ff.local", "ip": "10.5.0.5", "method": "RDP"}


@pytest.fixture(autouse=True)
def channel(sd, monkeypatch):  # noqa: F811
    mock = AsyncMock()
    monkeypatch.setattr(builds, "notify", mock)
    monkeypatch.setattr(jira_closure, "sd", service_requests.sd)
    return mock


def build_request(env, **kw) -> ServiceRequest:  # noqa: F811
    payload = {"order_number": 2001, "expected_return_at": (clock.today() + timedelta(days=30)).isoformat(),
               "requester_nick": "ivan", "os_label": "Debian 12", "purpose": "Нагрузочные тесты", "wanted_by": None}
    payload.update(kw.pop("payload", {}))
    kw.setdefault("issue_key", "DR-40")
    kw.setdefault("status", "Backlog")
    kw.setdefault("status_category", "new")
    return ServiceRequest(
        kind="build", user_id=env.owner.id, department_id=env.owner.department_id, payload=payload,
        summary="HMS Rent: сборка ПК — тип A (заказ №2001)",
        description="Проверить комплектующие.\n\nСборка: A — i9, 64 ГБ, RTX 4090\nОС: Debian 12\nЗаказ №2001", **kw,
    )


async def add_build(session, env, **kw) -> ServiceRequest:  # noqa: F811
    req = build_request(env, **kw)
    session.add(req)
    await session.commit()
    return req


async def built_pc(session, make_computer, name="A500", status=ComputerStatus.in_use.value, **kw) -> Computer:
    comp = await make_computer(name, None, status=status, **kw)
    return comp


async def pool_id(make_pool, name="Builds") -> int:
    return (await make_pool(name)).id


def issue(client, api, req, comp, pool, **over):
    return client.post(api(f"/executor/builds/{req.id}/issue"),
                       json={**FORM, "computer_name": comp if isinstance(comp, str) else comp.name, "pool_id": pool, **over})


# ---------- список и пулы ----------

async def test_list_shows_only_pending_orders_with_data(client, api, env, session, monkeypatch, sd):  # noqa: F811
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    first = await add_build(session, env, issue_key="DR-41")
    await add_build(session, env, issue_key="DR-42", portal_done_at=datetime.now(timezone.utc))  # уже обработан
    legacy = build_request(env, issue_key="DR-44")
    legacy.payload = null()  # SQL NULL, а не JSON null  # создан до миграции: выдать в портале нечего
    session.add_all([legacy, ServiceRequest(kind="return", user_id=env.owner.id, summary="s", description="d")])
    await session.commit()
    (row,) = (await client.get(api("/executor/builds"))).json()
    assert row["id"] == first.id and (row["request_key"], row["request_url"]) == ("DR-41", "https://jira.test/browse/DR-41")
    assert (row["order_number"], row["configuration"], row["os_label"], row["requester_nick"], row["purpose"]) == (
        2001, "A — i9, 64 ГБ, RTX 4090", "Debian 12", "ivan", "Нагрузочные тесты")
    assert (row["department"]["name"], row["user"]["username"], row["wanted_by"]) == ("QA", "owner", None)


async def test_pools_are_published_only_by_name(client, api, env, make_pool):  # noqa: F811
    await make_pool("Бета")
    await make_pool("Альфа")
    await make_pool("Черновик", is_published=False)
    assert [p["name"] for p in (await client.get(api("/executor/pools"))).json()] == ["Main", "Альфа", "Бета"]


# ---------- выдача ----------

async def test_issue_creates_booking_with_order_data_and_puts_pc_in_pool(client, api, env, session, make_computer, make_pool, sd):  # noqa: F811
    req = await add_build(session, env)
    comp = await built_pc(session, make_computer)
    pool = await pool_id(make_pool)
    r = await issue(client, api, req, "  a500 ", pool)  # имя без учёта регистра и пробелов
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["order_number"], body["computer"]["name"], body["connection_host"], body["connection_ip"]) == (
        2001, "A500", "A500.ff.local", "10.5.0.5")

    booking = (await session.scalars(select(Booking).where(Booking.order_number == 2001))).one()
    assert (booking.computer_id, booking.department_id, booking.user_id, booking.requester_nick, booking.os_label,
            booking.purpose, booking.expected_return_at) == (comp.id, env.owner.department_id, env.owner.id, "ivan",
                                                             "Debian 12", "Нагрузочные тесты", clock.today() + timedelta(days=30))
    assert (booking.connection_method, booking.prepared_by_id) == ("RDP", env.worker.id) and booking.prepared_at

    comp = (await session.scalars(select(Computer).where(Computer.id == comp.id).execution_options(populate_existing=True))).one()
    assert (comp.status, comp.pool_id, comp.department_id, comp.order_number, comp.usage_until) == (
        ComputerStatus.booked, pool, booking.department_id, 2001, booking.expected_return_at)
    events = [e for e in (await session.scalars(select(AssetEvent))).all() if e.computer_id == comp.id]
    assert {e.event_type for e in events} == {EventType.booked, EventType.prepared}

    (note,) = [n for n in (await session.scalars(select(Notification))).all() if n.kind == NotificationKind.pc_ready]
    assert note.user_id == env.owner.id
    await session.refresh(req)
    assert (req.booking_id, req.portal_done_at is not None) == (booking.id, True)
    assert (await client.get(api("/executor/builds"))).json() == []  # из списка ушёл
    assert (await issue(client, api, req, comp, pool)).status_code == 409  # повторно нельзя


async def test_issue_limits_long_term_and_opens_term_request(client, api, env, session, make_computer, make_pool, sd):  # noqa: F811
    far = clock.today() + timedelta(days=400)
    req = await add_build(session, env, payload={"expected_return_at": far.isoformat()})
    await built_pc(session, make_computer)
    assert (await issue(client, api, req, "A500", await pool_id(make_pool))).status_code == 200
    booking = (await session.scalars(select(Booking).where(Booking.order_number == 2001))).one()
    assert booking.expected_return_at < far  # без согласования — не дальше лимита
    (term,) = await session.scalars(select(TermRequest))
    assert (term.booking_id, term.requested_return_at) == (booking.id, far)


@pytest.mark.parametrize("status", ["in_use", "available", "unknown"])
async def test_issue_accepts_pcs_already_filled_in_insight(client, api, env, session, make_computer, make_pool, status, sd):  # noqa: F811
    req = await add_build(session, env)
    await built_pc(session, make_computer, status=status)
    assert (await issue(client, api, req, "A500", await pool_id(make_pool))).status_code == 200


@pytest.mark.parametrize("status, hint", [("booked", None), ("maintenance", None), ("cleaning", None), ("retired", "ещё «Закрыто»")])
async def test_issue_refuses_pcs_in_wrong_state(client, api, env, session, make_computer, make_pool, status, hint, sd):  # noqa: F811
    req = await add_build(session, env)
    await built_pc(session, make_computer, status=status)
    r = await issue(client, api, req, "A500", await pool_id(make_pool))
    assert r.status_code == 409 and "A500 сейчас нельзя выдать" in r.json()["detail"]
    if hint:
        assert hint in r.json()["detail"]


async def test_issue_refuses_archived_virtual_and_already_issued_pcs(client, api, env, session, make_computer, make_pool, sd):  # noqa: F811
    req = await add_build(session, env)
    pool = await pool_id(make_pool)
    await built_pc(session, make_computer, "A501", is_archived=True)
    await built_pc(session, make_computer, "A502", is_virtual=True)
    for name in ("A501", "A502"):
        assert (await issue(client, api, req, name, pool)).status_code == 409
    taken = await session.get(Computer, env.early.computer_id)  # у A001 активная бронь
    taken.status = ComputerStatus.in_use.value
    await session.commit()
    r = await issue(client, api, req, taken, pool)
    assert r.status_code == 409 and "уже выдан по другому заказу" in r.json()["detail"]


async def test_issue_not_found_and_validation(client, api, env, session, make_computer, make_pool, sd):  # noqa: F811
    req = await add_build(session, env)
    comp = await built_pc(session, make_computer)
    pool = await pool_id(make_pool)
    r = await issue(client, api, req, "A999", pool)
    assert r.status_code == 404 and "дождитесь синхронизации с Insight" in r.json()["detail"]
    assert (await issue(client, api, req, comp, 999999)).status_code == 404
    assert (await client.post(api("/executor/builds/999999/issue"), json={**FORM, "computer_name": "A500", "pool_id": pool})).status_code == 404
    for over in ({"ip": "не адрес"}, {"host": "bad host"}, {"method": "SSH"}, {"computer_name": ""}):
        assert (await issue(client, api, req, comp, pool, **over)).status_code == 422
    legacy = build_request(env, issue_key="DR-50")
    legacy.payload = null()  # SQL NULL, а не JSON null
    session.add(legacy)
    await session.commit()
    assert (await issue(client, api, legacy, comp, pool)).status_code == 409  # создан до миграции


async def test_customer_cannot_issue_or_reject(client, api, env, session, login, sd):  # noqa: F811
    req = await add_build(session, env)
    login(env.owner)
    assert (await client.get(api("/executor/builds"))).status_code == 403
    assert (await client.post(api(f"/executor/builds/{req.id}/issue"), json={**FORM, "computer_name": "A500", "pool_id": 1})).status_code == 403
    assert (await client.post(api(f"/executor/builds/{req.id}/reject"), json={"reason": "Некорректный заказ", "comment": "x"})).status_code == 403


# ---------- отклонение ----------

@pytest.mark.parametrize("reason", ["Нет комплектующих", "Несовместимая конфигурация", "Заказчик не ответил", "Некорректный заказ"])
async def test_reject_explains_to_customer_and_closes_order(client, api, env, session, reason, sd):  # noqa: F811
    req = await add_build(session, env)
    r = await client.post(api(f"/executor/builds/{req.id}/reject"), json={"reason": reason, "comment": "Нет подходящих плат"})
    assert r.status_code == 204
    await session.refresh(req)
    assert (req.resolution, req.portal_done_at is not None) == ("Rejected", True)
    (note,) = [n for n in (await session.scalars(select(Notification))).all() if n.kind == NotificationKind.order_rejected]
    assert note.user_id == env.owner.id and reason in note.title and "№2001" in note.title and "Нет подходящих плат" in note.body
    assert (await client.get(api("/executor/builds"))).json() == []
    assert (await client.post(api(f"/executor/builds/{req.id}/reject"), json={"reason": reason, "comment": "x"})).status_code == 409


@pytest.mark.parametrize("body", [{}, {"reason": "Некорректный заказ"}, {"reason": "Некорректный заказ", "comment": "  "},
                                  {"reason": "Сервер неисправен", "comment": "x"}, {"reason": "Некорректный заказ", "comment": "x" * 2001}],
                         ids=["empty", "no_comment", "spaces", "vm_reason", "too_long"])
async def test_reject_validation_422(client, api, env, session, body, sd):  # noqa: F811
    req = await add_build(session, env)
    assert (await client.post(api(f"/executor/builds/{req.id}/reject"), json=body)).status_code == 422


async def test_reject_unknown_or_other_kind_is_404(client, api, env, session, sd):  # noqa: F811
    other = ServiceRequest(kind="return", user_id=env.owner.id, summary="s", description="d", issue_key="X-1")
    session.add(other)
    await session.commit()
    body = {"reason": "Некорректный заказ", "comment": "x"}
    assert (await client.post(api("/executor/builds/999999/reject"), json=body)).status_code == 404
    assert (await client.post(api(f"/executor/builds/{other.id}/reject"), json=body)).status_code == 404


# ---------- портал закрывает задачу ----------

async def _round(session, status):
    async with SessionLocal() as s:
        for t in (await s.scalars(select(ServiceRequest))).unique():
            t.last_checked_at = None
        await s.commit()
    session.expire_all()
    service_requests.sd.status = real_sd.SdStatus(status, "new")
    await service_requests.refresh_open(session)


@pytest.mark.parametrize("action, resolution", [("issue", "Done"), ("reject", "Rejected")])
async def test_portal_closes_build_task_after_issue_or_reject(client, api, env, session, make_computer, make_pool, action, resolution, sd):  # noqa: F811
    req = await add_build(session, env)
    await built_pc(session, make_computer)
    await _round(session, "In Progress")
    assert sd.closed == []  # пока заказ не обработан, задача открыта
    if action == "issue":
        assert (await issue(client, api, req, "A500", await pool_id(make_pool))).status_code == 200
    else:
        assert (await client.post(api(f"/executor/builds/{req.id}/reject"),
                                  json={"reason": "Нет комплектующих", "comment": "x"})).status_code == 204
    await _round(session, "In Progress")
    assert sd.closed == [("DR-40", resolution)]


# ---------- отмена заказчиком ----------

async def test_customer_cancels_build_while_task_is_in_backlog(client, api, env, session, login, sd):  # noqa: F811
    req = await add_build(session, env)
    sd.status = real_sd.SdStatus("Backlog", "new")
    login(env.owner)
    assert (await client.post(api(f"/requests/{req.id}/cancel"))).status_code == 204
    await session.refresh(req)
    assert (req.resolution, req.portal_done_at is not None) == ("Rejected", True) and sd.status_calls == ["DR-40"]
    assert (await client.post(api(f"/requests/{req.id}/cancel"))).status_code == 409  # уже отменён
    login(env.worker)
    assert (await client.get(api("/executor/builds"))).json() == []


async def test_customer_cannot_cancel_taken_build(client, api, env, session, login, sd):  # noqa: F811
    req = await add_build(session, env)
    sd.status = real_sd.SdStatus("In Progress", "indeterminate")
    login(env.owner)
    r = await client.post(api(f"/requests/{req.id}/cancel"))
    assert r.status_code == 409 and "Исполнитель уже взял заказ в работу" in r.json()["detail"]
    await session.refresh(req)
    assert req.portal_done_at is None


async def test_cancel_access_and_kinds(client, api, env, session, login, make_user, make_department, sd):  # noqa: F811
    req = await add_build(session, env)
    qa = await session.get(Department, env.owner.department_id)
    mate = await make_user("mate", department=qa)
    other = ServiceRequest(kind="problem", user_id=env.owner.id, summary="s", description="d", issue_key="X-2")
    session.add(other)
    await session.commit()
    sd.status = real_sd.SdStatus("Backlog", "new")
    login(await make_user("stranger", department=await make_department("Ops")))
    assert (await client.post(api(f"/requests/{req.id}/cancel"))).status_code == 403
    assert (await client.post(api("/requests/999999/cancel"))).status_code == 404
    assert (await client.post(api(f"/requests/{other.id}/cancel"))).status_code == 404  # не сборка
    login(mate)  # коллега из той же команды может
    assert (await client.post(api(f"/requests/{req.id}/cancel"))).status_code == 204


async def test_cancel_is_refused_when_jira_is_down_and_allowed_without_jira(client, api, env, session, login, sd, monkeypatch):  # noqa: F811
    req = await add_build(session, env)
    sd.status_errors["DR-40"] = real_sd.ServiceDeskError("Service Desk недоступен")
    login(env.owner)
    r = await client.post(api(f"/requests/{req.id}/cancel"))
    assert r.status_code == 400 and "Не удалось проверить" in r.json()["detail"]
    monkeypatch.setattr(settings, "sd_token", "")  # Service Desk выключен: проверять нечего
    assert (await client.post(api(f"/requests/{req.id}/cancel"))).status_code == 204


async def test_requests_tell_whether_build_can_be_cancelled(client, api, env, session, login, sd):  # noqa: F811
    open_ = await add_build(session, env, issue_key="DR-60")
    await add_build(session, env, issue_key="DR-61", payload={"order_number": 2003}, portal_done_at=datetime.now(timezone.utc))
    login(env.owner)
    rows = {r["issue_key"]: r["can_cancel"] for r in (await client.get(api("/requests/my"))).json()}
    assert rows == {"DR-60": True, "DR-61": False} and open_.id


# ---------- закрыли в Jira ----------

async def _closed_in_jira(session, env, sd, resolution):  # noqa: F811
    req = await add_build(session, env, status="Done", status_category="done")
    sd.details = real_sd.SdDetails(taken=True, resolution=resolution)
    sd.comments = [real_sd.SdComment("Олег", "Нет плат", None, False)]
    await jira_closure.apply_closures(session)
    return req


async def test_build_rejected_in_jira_rejects_order(session, env, sd):  # noqa: F811
    req = await _closed_in_jira(session, env, sd, "Rejected")
    await session.refresh(req)
    assert (req.resolution, req.portal_done_at is not None, req.handled_at is not None) == ("Rejected", True, True)
    (note,) = [n for n in (await session.scalars(select(Notification))).all() if n.kind == NotificationKind.order_rejected]
    assert "Закрыто в Jira" in note.title and "Нет плат" in note.body


async def test_build_done_in_jira_without_issue_tells_customer(session, env, sd):  # noqa: F811
    req = await _closed_in_jira(session, env, sd, "Done")
    await session.refresh(req)
    assert req.portal_done_at is None and req.handled_at is not None  # заказ остаётся ждать выдачи в портале
    (note,) = [n for n in (await session.scalars(select(Notification))).all() if n.kind == NotificationKind.request_status]
    assert "завершил работу по заказу №2001 на сборку" in note.title and "Нет плат" in note.body


async def test_build_closed_in_jira_after_issue_changes_nothing(session, env, sd):  # noqa: F811
    req = await add_build(session, env, status="Done", status_category="done", portal_done_at=datetime.now(timezone.utc))
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await jira_closure.apply_closures(session)
    assert (await session.scalars(select(Notification))).all() == [] and req.id
