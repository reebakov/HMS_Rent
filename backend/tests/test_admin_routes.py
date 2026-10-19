"""Админские маршруты из api/routes/admin.py: сводка, инвентаризация, ПК, пулы, журналы, отделы, синхронизация.

Доступ неадминов проверяет test_api_access.py — здесь только поведение под админом.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AssetEvent, Booking, Computer, Department, EventType, Pool, SyncRun, UserRole
from app.models.pool import pool_departments
from tests.sync_fakes import FakeInsight, add_booking, insight_obj, patch_source

ADMIN = UserRole.admin.value
TODAY = date.today()


@pytest.fixture
async def boss(login, make_user):
    """Админ, под которым клиент уже залогинен."""
    user = await make_user("boss", role=ADMIN, display_name="Босс")
    login(user)
    return user


async def fresh(model, obj_id):
    """Свежая запись из БД (отдельная сессия — test-сессия может держать устаревший объект)."""
    async with SessionLocal() as s:
        return await s.get(model, obj_id)


async def count(model) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count()).select_from(model))


async def add_ev(session, comp, event_type=EventType.admin_update, message="", created_at=None, **kw) -> AssetEvent:
    ev = AssetEvent(computer_id=comp.id, event_type=event_type, message=message,
                    **({"created_at": created_at} if created_at else {}), **kw)
    session.add(ev)
    await session.commit()
    return ev


# ---------- /stats ----------

async def test_stats_empty_portal(client, boss, api):
    r = await client.get(api("/admin/stats"))
    assert r.status_code == 200
    assert r.json() == {
        "total": 0, "by_status": {}, "in_pools": 0, "active_bookings": 0, "departments_using": 0,
        "overdue": 0, "issues": 0, "last_sync": None,
        "by_tier": [{"tier": t, "total": 0, "available": 0, "booked": 0} for t in ("weak", "medium", "powerful", "vm")],
    }


async def test_stats_counts(client, boss, api, session, make_computer, make_pool, make_department):
    dept, pool = await make_department("QA"), await make_pool("Main")
    await make_computer("A1", pool, tier="weak")
    booked = await make_computer("A2", pool, status="booked", tier="powerful")
    await make_computer("A3", status="maintenance", tier="weak")
    await make_computer("A4", is_archived=True, tier="vm")  # архивный не считается нигде
    await add_booking(session, booked, boss, dept, expected_return_at=TODAY - timedelta(days=1))
    session.add(SyncRun(mode="mock", status="success", total=3))
    await session.commit()

    body = (await client.get(api("/admin/stats"))).json()
    assert body["total"] == 3
    assert body["by_status"] == {"available": 1, "booked": 1, "maintenance": 1}
    assert body["in_pools"] == 2
    assert (body["active_bookings"], body["departments_using"], body["overdue"]) == (1, 1, 1)
    assert body["issues"] == 1  # просроченный возврат
    tiers = {t["tier"]: t for t in body["by_tier"]}
    assert tiers["weak"] == {"tier": "weak", "total": 2, "available": 1, "booked": 0}
    assert tiers["powerful"] == {"tier": "powerful", "total": 1, "available": 0, "booked": 1}
    assert tiers["vm"]["total"] == 0
    assert body["last_sync"]["status"] == "success" and body["last_sync"]["total"] == 3


# ---------- /inventory ----------

async def test_inventory_row_shape_and_booking(client, boss, api, session, make_computer, make_pool, make_department):
    dept, pool = await make_department("QA"), await make_pool("Main", description="d")
    comp = await make_computer("A1", pool, status="booked", serial_number="SN1", note="заметка", tier_override="weak",
                               ram_gb=16, usage_until=TODAY, order_number=1001)
    await add_booking(session, comp, boss, dept, requester_name="Пётр", requester_nick="pete")
    body = (await client.get(api("/admin/inventory"))).json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["name"] == "A1" and row["serial_number"] == "SN1" and row["note"] == "заметка"
    assert row["tier_override"] == "weak" and row["is_archived"] is False and row["order_number"] == 1001
    assert row["pool"] == {"id": pool.id, "name": "Main", "is_published": True}
    assert row["booking"]["requester_name"] == "Пётр" and row["booking"]["requester_nick"] == "pete"
    assert row["booking"]["user"]["username"] == "boss"
    assert row["issues"] == [] and row["writeback_error"] is None


async def test_inventory_filters_via_query(client, boss, api, make_computer, make_pool, make_department):
    dept, pool = await make_department("QA"), await make_pool("Main")
    await make_computer("A1", pool, tier="weak", cpu="Intel")
    await make_computer("A2", status="maintenance", tier="powerful", department_id=dept.id)
    await make_computer("A3", is_archived=True)

    async def names(**params):
        r = await client.get(api("/admin/inventory"), params=params)
        assert r.status_code == 200
        return [i["name"] for i in r.json()["items"]]

    assert await names() == ["A1", "A2"]
    assert await names(include_archived="true") == ["A1", "A2", "A3"]
    assert await names(status="maintenance") == ["A2"]
    assert await names(status="unavailable") == ["A2"]
    assert await names(tier="weak") == ["A1"]
    assert await names(department_id=dept.id) == ["A2"]
    assert await names(pool_id=pool.id) == ["A1"]
    assert await names(pool_id="none") == ["A2"]
    assert await names(q="intel") == ["A1"]
    assert await names(issues_only="true") == []


async def test_inventory_issues_only_returns_flagged_computers(client, boss, api, session, make_computer, make_department):
    dept = await make_department("QA")
    await make_computer("A1")
    late = await make_computer("A2", status="booked")
    await make_computer("A3", writeback_error="boom")
    await add_booking(session, late, boss, dept, expected_return_at=TODAY - timedelta(days=3))
    body = (await client.get(api("/admin/inventory"), params={"issues_only": "true"})).json()
    assert [i["name"] for i in body["items"]] == ["A2", "A3"] and body["total"] == 2
    assert any("Просрочен возврат" in s for s in body["items"][0]["issues"])
    assert "Ошибка записи в Insight: boom" in body["items"][1]["issues"]


async def test_inventory_pagination(client, boss, api, make_computer):
    for _ in range(3):
        await make_computer()
    r = (await client.get(api("/admin/inventory"), params={"limit": 2, "offset": 1})).json()
    assert r["total"] == 3 and [i["name"] for i in r["items"]] == ["A002", "A003"]


@pytest.mark.parametrize("path, params", [
    ("/admin/inventory", {"limit": 0}), ("/admin/inventory", {"limit": -1}), ("/admin/inventory", {"limit": 501}),
    ("/admin/inventory", {"limit": "abc"}), ("/admin/inventory", {"offset": -1}),
    ("/admin/events", {"limit": 0}), ("/admin/events", {"limit": -1}), ("/admin/events", {"limit": 501}),
    ("/admin/events", {"offset": -1}),
], ids=lambda v: str(v))
async def test_page_bounds_are_client_error(client, boss, api, path, params):
    """limit вне 1..500 и отрицательный offset — 422: раньше limit=0 отдавал всё, а offset<0 ронял запрос (500)."""
    assert (await client.get(api(path), params=params)).status_code == 422


@pytest.mark.parametrize("path", ["/admin/inventory", "/admin/events"])
async def test_page_upper_bound_is_accepted(client, boss, api, path):
    assert (await client.get(api(path), params={"limit": 500, "offset": 0})).status_code == 200


async def test_inventory_non_numeric_pool_id_is_client_error(client, boss, api):
    r = await client.get(api("/admin/inventory"), params={"pool_id": "abc"})
    assert r.status_code == 422
    assert (await client.get(api("/admin/inventory/export"), params={"pool_id": "1; DROP"})).status_code == 422


# ---------- /inventory/export ----------

async def test_export_csv(client, boss, api, make_computer, make_pool):
    pool = await make_pool("Main")
    await make_computer("A1", pool, cpu="Intel")
    await make_computer("A2")
    r = await client.get(api("/admin/inventory/export"))
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="inventory_{TODAY:%Y-%m-%d}.csv"'
    assert r.content.startswith("﻿".encode())
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("ПК;Ключ Insight;Категория")
    assert len(lines) == 3 and lines[1].startswith("A1;") and "Intel" in lines[1] and "Main" in lines[1]


async def test_export_filters_and_excludes_archived(client, boss, api, make_computer, make_pool):
    pool = await make_pool("Main")
    await make_computer("A1", pool)
    await make_computer("A2")
    await make_computer("A3", pool, is_archived=True)
    by_pool = (await client.get(api("/admin/inventory/export"), params={"pool_id": pool.id})).content.decode("utf-8-sig")
    assert [row.split(";")[0] for row in by_pool.splitlines()[1:]] == ["A1"]
    no_pool = (await client.get(api("/admin/inventory/export"), params={"pool_id": "none"})).content.decode("utf-8-sig")
    assert [row.split(";")[0] for row in no_pool.splitlines()[1:]] == ["A2"]


async def test_export_empty_has_only_header(client, boss, api):
    r = await client.get(api("/admin/inventory/export"))
    assert len(r.content.decode("utf-8-sig").splitlines()) == 1


# ---------- GET /computers/{id} ----------

async def test_computer_history_shape_and_order(client, boss, api, session, make_computer, make_department, make_user):
    dept, other = await make_department("QA"), await make_user("u2")
    comp = await make_computer("A1", status="booked", attributes={"Дисплей": "27"})
    old = await add_booking(session, comp, other, dept, status="returned",
                            booked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    cur = await add_booking(session, comp, boss, dept)
    await add_ev(session, comp, EventType.booked, "Забронирован", booking_id=cur.id, actor_id=boss.id)
    await add_ev(session, comp, EventType.returned, "Возврат", booking_id=old.id)

    body = (await client.get(api(f"/admin/computers/{comp.id}"))).json()
    assert set(body) == {"computer", "attributes", "bookings", "events"}
    assert body["computer"]["name"] == "A1" and body["computer"]["booking"]["id"] == cur.id
    assert body["attributes"] == {"Дисплей": "27"}
    assert [b["id"] for b in body["bookings"]] == [cur.id, old.id]  # свежие первыми
    assert body["bookings"][0]["computer"]["name"] == "A1" and body["bookings"][0]["status"] == "active"
    assert [e["message"] for e in body["events"]] == ["Возврат", "Забронирован"]  # новые первыми
    assert body["events"][1]["actor"]["username"] == "boss" and body["events"][0]["computer"]["name"] == "A1"


async def test_computer_history_without_booking_and_foreign_events(client, boss, api, session, make_computer):
    a, b = await make_computer("A1"), await make_computer("A2")
    await add_ev(session, b, message="чужое")
    body = (await client.get(api(f"/admin/computers/{a.id}"))).json()
    assert body["bookings"] == [] and body["events"] == [] and body["computer"]["booking"] is None
    assert body["attributes"] == {}


async def test_computer_history_works_for_archived(client, boss, api, make_computer):
    comp = await make_computer("A1", is_archived=True)
    r = await client.get(api(f"/admin/computers/{comp.id}"))
    assert r.status_code == 200 and r.json()["computer"]["is_archived"] is True


async def test_computer_history_404(client, boss, api):
    r = await client.get(api("/admin/computers/999"))
    assert r.status_code == 404 and r.json()["detail"] == "Компьютер не найден"


# ---------- PATCH /computers/{id} ----------

async def test_update_computer_tier_override_sets_tier(client, boss, api, make_computer):
    comp = await make_computer("A1", ram_gb=8, tier="weak")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"tier_override": "powerful"})
    assert r.status_code == 200
    assert r.json()["tier"] == "powerful" and r.json()["tier_override"] == "powerful"
    db = await fresh(Computer, comp.id)
    assert (db.tier, db.tier_override) == ("powerful", "powerful")


async def test_update_computer_clearing_override_reclassifies(client, boss, api, make_computer):
    comp = await make_computer("A1", ram_gb=32, tier="weak", tier_override="weak")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"tier_override": None})
    assert r.status_code == 200
    assert r.json()["tier_override"] is None and r.json()["tier"] == "powerful"  # 32 ГБ — мощный
    db = await fresh(Computer, comp.id)
    assert (db.tier, db.tier_override) == ("powerful", None)


async def test_update_computer_clearing_override_of_virtual_gives_vm(client, boss, api, make_computer):
    comp = await make_computer("V1", is_virtual=True, ram_gb=64, tier="powerful", tier_override="powerful")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"tier_override": None})
    assert r.json()["tier"] == "vm"


async def test_update_computer_note_set_and_clear(client, boss, api, make_computer):
    comp = await make_computer("A1", tier="weak", tier_override="weak")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"note": "Сломан кулер"})
    assert r.json()["note"] == "Сломан кулер"
    assert (await fresh(Computer, comp.id)).tier_override == "weak"  # note не трогает категорию
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"note": ""})
    assert r.json()["note"] is None and (await fresh(Computer, comp.id)).note is None


async def test_update_computer_event_logged_with_actor_and_payload(client, boss, api, session, make_computer):
    comp = await make_computer("A1")
    await client.patch(api(f"/admin/computers/{comp.id}"), json={"tier_override": "vm", "note": "x"})
    (ev,) = (await session.scalars(select(AssetEvent).where(AssetEvent.computer_id == comp.id))).unique().all()
    assert ev.event_type == EventType.admin_update and ev.actor_id == boss.id
    assert ev.message == "Изменено админом: tier_override, note"
    assert ev.payload == {"tier_override": "vm", "note": "x"}


async def test_update_computer_empty_body_is_noop_event(client, boss, api, session, make_computer):
    comp = await make_computer("A1", tier="medium")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={})
    assert r.status_code == 200 and r.json()["tier"] == "medium"
    (ev,) = (await session.scalars(select(AssetEvent).where(AssetEvent.computer_id == comp.id))).unique().all()
    assert ev.message == "Без изменений" and ev.payload == {}


async def test_update_computer_returns_active_booking(client, boss, api, session, make_computer, make_department):
    comp = await make_computer("A1", status="booked")
    await add_booking(session, comp, boss, await make_department("QA"))
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"note": "n"})
    assert r.json()["booking"]["requester_nick"] == "ivan"


@pytest.mark.parametrize("body", [{"tier_override": "super"}, {"tier_override": 5}, {"note": "x" * 2001}])
async def test_update_computer_validation(client, boss, api, make_computer, body):
    comp = await make_computer("A1", tier="medium")
    assert (await client.patch(api(f"/admin/computers/{comp.id}"), json=body)).status_code == 422
    db = await fresh(Computer, comp.id)
    assert db.tier == "medium" and db.tier_override is None and db.note is None
    assert await count(AssetEvent) == 0


async def test_update_computer_note_boundary_ok(client, boss, api, make_computer):
    comp = await make_computer("A1")
    assert (await client.patch(api(f"/admin/computers/{comp.id}"), json={"note": "x" * 2000})).status_code == 200


async def test_update_computer_404(client, boss, api):
    r = await client.patch(api("/admin/computers/999"), json={"note": "x"})
    assert r.status_code == 404 and r.json()["detail"] == "Компьютер не найден"


async def test_update_computer_cannot_change_status_or_pool(client, boss, api, make_computer):
    """Статус «железа» меняется только в Insight; лишние поля тела игнорируются."""
    comp = await make_computer("A1")
    r = await client.patch(api(f"/admin/computers/{comp.id}"), json={"status": "retired", "pool_id": 5, "name": "Z"})
    assert r.status_code == 200
    db = await fresh(Computer, comp.id)
    assert (db.status, db.pool_id, db.name) == ("available", None, "A1")


# ---------- Пулы: список ----------

async def test_list_pools_shape_and_counts(client, boss, api, make_pool, make_computer, make_department):
    dept = await make_department("QA")
    pool = await make_pool("A-pool", departments=[dept], description="Описание")
    await make_computer("A1", pool)
    await make_computer("A2", pool, status="booked")
    await make_pool("B-pool", is_published=False)
    body = (await client.get(api("/admin/pools"))).json()
    assert [p["name"] for p in body] == ["A-pool", "B-pool"]
    assert body[0] == {"id": pool.id, "name": "A-pool", "is_published": True, "description": "Описание",
                       "departments": [{"id": dept.id, "name": "QA"}], "total": 2, "available": 1, "booked": 1}
    assert body[1]["is_published"] is False and body[1]["total"] == 0 and body[1]["departments"] == []


# ---------- Пулы: создание ----------

async def test_create_pool_defaults(client, boss, api):
    r = await client.post(api("/admin/pools"), json={"name": "  Main  "})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Main" and body["is_published"] is True and body["description"] is None
    assert body["departments"] == [] and (body["total"], body["available"], body["booked"]) == (0, 0, 0)
    assert (await fresh(Pool, body["id"])).name == "Main"


async def test_create_pool_with_departments_and_flags(client, boss, api, make_department):
    d1, d2 = await make_department("QA"), await make_department("Dev")
    r = await client.post(api("/admin/pools"), json={"name": "Closed", "description": "Только QA/Dev",
                                                     "is_published": False, "department_ids": [d1.id, d2.id, d1.id]})
    assert r.status_code == 201
    body = r.json()
    assert body["is_published"] is False and body["description"] == "Только QA/Dev"
    assert sorted(d["name"] for d in body["departments"]) == ["Dev", "QA"]
    async with SessionLocal() as s:
        links = (await s.execute(select(pool_departments.c.department_id).where(pool_departments.c.pool_id == body["id"]))).scalars().all()
    assert sorted(links) == sorted([d1.id, d2.id])


async def test_create_pool_duplicate_name_409(client, boss, api, make_pool):
    await make_pool("Main")
    r = await client.post(api("/admin/pools"), json={"name": "Main"})
    assert r.status_code == 409 and r.json()["detail"] == "Пул с таким названием уже есть"
    assert await count(Pool) == 1
    # после отката сессия жива: следующий запрос проходит
    assert (await client.post(api("/admin/pools"), json={"name": "Other"})).status_code == 201


async def test_create_pool_duplicate_detected_after_trim(client, boss, api, make_pool):
    await make_pool("Main")
    assert (await client.post(api("/admin/pools"), json={"name": " Main "})).status_code == 409


@pytest.mark.parametrize("body", [{}, {"name": None}, {"name": "A"}, {"name": "x" * 256},
                                  {"name": "Ok", "description": "d" * 2001}, {"name": "Ok", "is_published": "maybe"},
                                  {"name": "Ok", "department_ids": "1"}])
async def test_create_pool_validation_422(client, boss, api, body):
    assert (await client.post(api("/admin/pools"), json=body)).status_code == 422
    assert await count(Pool) == 0


async def test_create_pool_unknown_department_404_nothing_created(client, boss, api, make_department):
    d = await make_department("QA")
    r = await client.post(api("/admin/pools"), json={"name": "Main", "department_ids": [d.id, 999]})
    assert r.status_code == 404 and r.json()["detail"] == "Один из отделов не найден"
    assert await count(Pool) == 0


async def test_create_pool_whitespace_only_name_rejected(client, boss, api):
    r = await client.post(api("/admin/pools"), json={"name": "   "})
    assert r.status_code == 422


# ---------- Пулы: правка ----------

async def test_update_pool_fields(client, boss, api, make_pool):
    pool = await make_pool("Old", description="d", is_published=True)
    r = await client.patch(api(f"/admin/pools/{pool.id}"),
                           json={"name": " New ", "description": " text ", "is_published": False})
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["description"], r.json()["is_published"]) == ("New", "text", False)
    db = await fresh(Pool, pool.id)
    assert (db.name, db.description, db.is_published) == ("New", "text", False)


async def test_update_pool_partial_keeps_other_fields(client, boss, api, make_pool, make_department):
    dept = await make_department("QA")
    pool = await make_pool("Main", departments=[dept], description="d")
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"is_published": False})
    body = r.json()
    assert body["name"] == "Main" and body["description"] == "d" and body["departments"] == [{"id": dept.id, "name": "QA"}]


async def test_update_pool_empty_body_is_noop(client, boss, api, make_pool):
    pool = await make_pool("Main")
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={})
    assert r.status_code == 200 and r.json()["name"] == "Main"


async def test_update_pool_replace_and_clear_departments(client, boss, api, make_pool, make_department):
    d1, d2 = await make_department("QA"), await make_department("Dev")
    pool = await make_pool("Main", departments=[d1])
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"department_ids": [d2.id]})
    assert r.json()["departments"] == [{"id": d2.id, "name": "Dev"}]
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"department_ids": []})
    assert r.json()["departments"] == []  # пусто — виден всем
    async with SessionLocal() as s:
        assert (await s.scalar(select(func.count()).select_from(pool_departments))) == 0


async def test_update_pool_unknown_department_404_and_unchanged(client, boss, api, make_pool, make_department):
    d1 = await make_department("QA")
    pool = await make_pool("Main", departments=[d1])
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"name": "Renamed", "department_ids": [999]})
    assert r.status_code == 404 and r.json()["detail"] == "Один из отделов не найден"
    assert (await fresh(Pool, pool.id)).name == "Main"
    async with SessionLocal() as s:
        assert (await s.scalar(select(func.count()).select_from(pool_departments))) == 1


async def test_update_pool_duplicate_name_409(client, boss, api, make_pool):
    await make_pool("AA")
    b = await make_pool("BB")
    r = await client.patch(api(f"/admin/pools/{b.id}"), json={"name": "AA"})
    assert r.status_code == 409 and r.json()["detail"] == "Пул с таким названием уже есть"
    assert (await fresh(Pool, b.id)).name == "BB"
    assert (await client.patch(api(f"/admin/pools/{b.id}"), json={"name": "CC"})).status_code == 200


async def test_update_pool_same_name_is_ok(client, boss, api, make_pool):
    pool = await make_pool("AA")
    assert (await client.patch(api(f"/admin/pools/{pool.id}"), json={"name": "AA"})).status_code == 200


async def test_update_pool_404(client, boss, api):
    r = await client.patch(api("/admin/pools/999"), json={"name": "X1"})
    assert r.status_code == 404 and r.json()["detail"] == "Пул не найден"


@pytest.mark.parametrize("body", [{"name": "A"}, {"name": "x" * 256}, {"description": "d" * 2001},
                                  {"is_published": "maybe"}, {"department_ids": "x"}])
async def test_update_pool_validation_422(client, boss, api, make_pool, body):
    pool = await make_pool("Main")
    assert (await client.patch(api(f"/admin/pools/{pool.id}"), json=body)).status_code == 422


async def test_update_pool_null_name_is_validation_error(client, boss, api, make_pool):
    pool = await make_pool("Main")
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"name": None})
    assert r.status_code == 422


async def test_update_pool_response_has_real_counters(client, boss, api, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1", pool)
    r = await client.patch(api(f"/admin/pools/{pool.id}"), json={"description": "x"})
    assert r.json()["total"] == 1 and r.json()["available"] == 1 and r.json()["booked"] == 0


# ---------- Пулы: удаление ----------

async def test_delete_pool_204_detaches_computers(client, boss, api, make_pool, make_computer, make_department):
    dept = await make_department("QA")
    pool = await make_pool("Main", departments=[dept])
    comp = await make_computer("A1", pool)
    r = await client.delete(api(f"/admin/pools/{pool.id}"))
    assert r.status_code == 204 and r.content == b""
    assert await fresh(Pool, pool.id) is None
    assert (await fresh(Computer, comp.id)).pool_id is None
    assert await fresh(Department, dept.id) is not None


async def test_delete_pool_404(client, boss, api):
    r = await client.delete(api("/admin/pools/999"))
    assert r.status_code == 404 and r.json()["detail"] == "Пул не найден"


async def test_delete_pool_with_booked_409(client, boss, api, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1", pool, status="booked")
    r = await client.delete(api(f"/admin/pools/{pool.id}"))
    assert r.status_code == 409 and "1 забронированных" in r.json()["detail"]
    assert await fresh(Pool, pool.id) is not None


# ---------- Пулы: массовое назначение ----------

async def test_assign_endpoint_by_names(client, boss, api, make_pool, make_computer):
    pool = await make_pool("Main")
    a = await make_computer("A1")
    await make_computer("A2")
    r = await client.post(api("/admin/pools/assign"), json={"pool_id": pool.id, "names": "a1, ghost"})
    assert r.status_code == 200 and r.json() == {"updated": 1, "not_found": ["ghost"]}
    assert (await fresh(Computer, a.id)).pool_id == pool.id


async def test_assign_endpoint_by_ids_then_remove(client, boss, api, session, make_pool, make_computer):
    pool = await make_pool("Main")
    a, b = await make_computer("A1"), await make_computer("A2")
    r = await client.post(api("/admin/pools/assign"), json={"pool_id": pool.id, "computer_ids": [a.id, b.id]})
    assert r.json() == {"updated": 2, "not_found": []}
    r = await client.post(api("/admin/pools/assign"), json={"pool_id": None, "computer_ids": [a.id]})
    assert r.json() == {"updated": 1, "not_found": []}
    assert (await fresh(Computer, a.id)).pool_id is None and (await fresh(Computer, b.id)).pool_id == pool.id
    msgs = (await session.scalars(select(AssetEvent.message).where(AssetEvent.computer_id == a.id).order_by(AssetEvent.id))).all()
    assert msgs == ["Пул: — → Main", "Пул: Main → —"]


async def test_assign_endpoint_empty_input(client, boss, api, make_pool):
    pool = await make_pool("Main")
    r = await client.post(api("/admin/pools/assign"), json={"pool_id": pool.id, "names": ""})
    assert r.status_code == 200 and r.json() == {"updated": 0, "not_found": []}


async def test_assign_endpoint_unknown_pool_404(client, boss, api, make_computer):
    comp = await make_computer("A1")
    r = await client.post(api("/admin/pools/assign"), json={"pool_id": 999, "computer_ids": [comp.id]})
    assert r.status_code == 404 and r.json()["detail"] == "Пул не найден"


@pytest.mark.parametrize("body", [{}, {"pool_id": "x"}, {"pool_id": 1, "computer_ids": "1"},
                                  {"pool_id": 1, "computer_ids": ["a"]}, {"pool_id": 1, "names": "x" * 100_001}])
async def test_assign_endpoint_validation_422(client, boss, api, make_pool, body):
    await make_pool("Main")
    assert (await client.post(api("/admin/pools/assign"), json=body)).status_code == 422


# ---------- /bookings (журнал выдачи) ----------

@pytest.fixture
async def journal_data(session, boss, make_user, make_department, make_computer):
    qa, dev = await make_department("QA"), await make_department("Dev")
    u = await make_user("emp")
    c1, c2, c3 = await make_computer("A1"), await make_computer("B2"), await make_computer("C3")
    b1 = await add_booking(session, c1, u, qa, status="returned", requester_name="Анна", requester_nick="anya",
                           booked_at=datetime(2026, 3, 1, 10, tzinfo=timezone.utc))
    b2 = await add_booking(session, c2, u, dev, requester_name="Борис", requester_nick="bob",
                           booked_at=datetime(2026, 3, 10, 10, tzinfo=timezone.utc))
    b3 = await add_booking(session, c3, u, qa, requester_name="Вера", requester_nick="vera",
                           booked_at=datetime(2026, 3, 20, 10, tzinfo=timezone.utc))
    return {"qa": qa, "dev": dev, "b": [b1, b2, b3]}


async def journal_ids(client, api, **params):
    r = await client.get(api("/admin/bookings"), params=params)
    assert r.status_code == 200, r.text
    return [b["id"] for b in r.json()]


async def test_journal_order_and_shape(client, api, journal_data):
    b1, b2, b3 = journal_data["b"]
    r = await client.get(api("/admin/bookings"))
    body = r.json()
    assert [b["id"] for b in body] == [b3.id, b2.id, b1.id]  # свежие первыми
    row = body[0]
    assert row["computer"]["name"] == "C3" and row["department"]["name"] == "QA" and row["user"]["username"] == "emp"
    assert row["requester_name"] == "Вера" and row["status"] == "active" and row["returned_at"] is None
    assert row["order_number"] > 1000 and set(row) >= {"purpose", "booked_at", "expected_return_at", "returned_by"}


async def test_journal_filters(client, api, journal_data):
    b1, b2, b3 = journal_data["b"]
    assert await journal_ids(client, api, status="returned") == [b1.id]
    assert await journal_ids(client, api, status="active") == [b3.id, b2.id]
    assert await journal_ids(client, api, department_id=journal_data["dev"].id) == [b2.id]
    assert await journal_ids(client, api, q="вера") == [b3.id]       # по заявителю, без учёта регистра
    assert await journal_ids(client, api, q="BOB") == [b2.id]        # по нику
    assert await journal_ids(client, api, q="a1") == [b1.id]         # по имени ПК
    assert await journal_ids(client, api, q="нет-такого") == []


async def test_journal_date_range_inclusive(client, api, journal_data):
    b1, b2, b3 = journal_data["b"]
    assert await journal_ids(client, api, date_from="2026-03-10") == [b3.id, b2.id]
    assert await journal_ids(client, api, date_to="2026-03-10") == [b2.id, b1.id]  # весь день date_to включён
    assert await journal_ids(client, api, date_from="2026-03-05", date_to="2026-03-15") == [b2.id]
    assert await journal_ids(client, api, date_from="2026-04-01") == []


async def test_journal_bad_date_422(client, boss, api):
    assert (await client.get(api("/admin/bookings"), params={"date_from": "вчера"})).status_code == 422


# ---------- /events ----------

@pytest.fixture
async def events_data(session, boss, make_computer):
    c1, c2 = await make_computer("A1"), await make_computer("B2")
    e1 = await add_ev(session, c1, EventType.booked, "Бронь старая", created_at=datetime(2026, 2, 1, 12, tzinfo=timezone.utc))
    e2 = await add_ev(session, c2, EventType.returned, "Возврат ПК", created_at=datetime(2026, 2, 5, 12, tzinfo=timezone.utc),
                      actor_id=boss.id)
    e3 = await add_ev(session, c1, EventType.admin_update, "Пул: — → Main",
                      created_at=datetime(2026, 2, 9, 12, tzinfo=timezone.utc), from_status="a", to_status="b")
    return [e1, e2, e3]


async def event_ids(client, api, **params):
    r = await client.get(api("/admin/events"), params=params)
    assert r.status_code == 200, r.text
    return [e["id"] for e in r.json()["items"]]


async def test_events_page_shape_and_order(client, api, events_data):
    e1, e2, e3 = events_data
    body = (await client.get(api("/admin/events"))).json()
    assert set(body) == {"items", "total"} and body["total"] == 3
    assert [e["id"] for e in body["items"]] == [e3.id, e2.id, e1.id]  # новые первыми
    first, second = body["items"][0], body["items"][1]
    assert first["computer"] == {"id": e3.computer_id, "name": "A1"} and first["event_type"] == "admin_update"
    assert (first["from_status"], first["to_status"], first["actor"]) == ("a", "b", None)
    assert second["actor"]["username"] == "boss" and second["message"] == "Возврат ПК"


async def test_events_filters(client, api, events_data):
    e1, e2, e3 = events_data
    assert await event_ids(client, api, event_type="returned") == [e2.id]
    assert await event_ids(client, api, q="пул") == [e3.id]            # по тексту
    assert await event_ids(client, api, q="b2") == [e2.id]             # по имени ПК
    assert await event_ids(client, api, date_from="2026-02-05") == [e3.id, e2.id]
    assert await event_ids(client, api, date_to="2026-02-05") == [e2.id, e1.id]
    assert await event_ids(client, api, event_type="booked", q="нет") == []


async def test_events_pagination_total_is_not_limited(client, api, events_data):
    e1, e2, e3 = events_data
    r = (await client.get(api("/admin/events"), params={"limit": 1, "offset": 1})).json()
    assert r["total"] == 3 and [e["id"] for e in r["items"]] == [e2.id]
    r = (await client.get(api("/admin/events"), params={"limit": 2, "offset": 2})).json()
    assert [e["id"] for e in r["items"]] == [e1.id]
    assert (await client.get(api("/admin/events"), params={"offset": 10})).json() == {"items": [], "total": 3}


async def test_events_empty(client, boss, api):
    assert (await client.get(api("/admin/events"))).json() == {"items": [], "total": 0}


@pytest.mark.parametrize("params", [{"limit": "x"}, {"offset": "x"}, {"date_to": "bad"}])
async def test_events_bad_params_422(client, boss, api, params):
    assert (await client.get(api("/admin/events"), params=params)).status_code == 422


# ---------- Отделы ----------

async def test_departments_usage(client, boss, api, session, make_department, make_computer, make_user):
    qa, dev = await make_department("QA", code="Q", head_name="Шеф"), await make_department("Dev", is_active=False)
    await make_department("Idle")
    u = await make_user("emp")
    weak, power = await make_computer("A1", tier="weak", status="booked"), await make_computer("A2", tier="powerful", status="booked")
    old = await make_computer("A3", tier="weak")
    await add_booking(session, weak, u, dev, booked_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    await add_booking(session, power, u, dev)
    await add_booking(session, old, u, qa, status="returned", booked_at=datetime(2026, 2, 2, tzinfo=timezone.utc))

    body = (await client.get(api("/admin/departments"))).json()
    assert [d["name"] for d in body] == ["Dev", "Idle", "QA"]  # сначала по числу активных, потом по имени
    by = {d["name"]: d for d in body}
    assert by["Dev"]["active"] == 2 and by["Dev"]["by_tier"] == {"weak": 1, "powerful": 1}
    assert by["Dev"]["total_bookings"] == 2 and by["Dev"]["is_active"] is False
    assert by["QA"]["active"] == 0 and by["QA"]["by_tier"] == {} and by["QA"]["total_bookings"] == 1
    assert by["QA"]["code"] == "Q" and by["QA"]["head_name"] == "Шеф"
    assert by["QA"]["last_booked_at"].startswith("2026-02-02")
    assert by["Idle"]["total_bookings"] == 0 and by["Idle"]["last_booked_at"] is None


async def test_create_department(client, boss, api):
    r = await client.post(api("/admin/departments"), json={"name": "  QA  ", "code": "qa-1", "head_name": "Иванов"})
    assert r.status_code == 201
    body = r.json()
    assert (body["name"], body["code"], body["head_name"], body["is_active"]) == ("QA", "qa-1", "Иванов", True)
    assert (await fresh(Department, body["id"])).name == "QA"


async def test_create_department_minimal(client, boss, api):
    r = await client.post(api("/admin/departments"), json={"name": "HR"})
    assert r.status_code == 201 and r.json()["code"] is None and r.json()["head_name"] is None


async def test_create_department_duplicate_409(client, boss, api, make_department):
    await make_department("QA")
    r = await client.post(api("/admin/departments"), json={"name": "QA"})
    assert r.status_code == 409 and r.json()["detail"] == "Отдел с таким названием уже есть"
    assert await count(Department) == 1
    assert (await client.post(api("/admin/departments"), json={"name": "Dev"})).status_code == 201


@pytest.mark.parametrize("body", [{}, {"name": "A"}, {"name": "x" * 256}, {"name": "OK", "code": "c" * 65},
                                  {"name": "OK", "head_name": "h" * 256}, {"name": None}])
async def test_create_department_validation_422(client, boss, api, body):
    assert (await client.post(api("/admin/departments"), json=body)).status_code == 422
    assert await count(Department) == 0


async def test_create_department_whitespace_name_rejected(client, boss, api):
    assert (await client.post(api("/admin/departments"), json={"name": "   "})).status_code == 422


async def test_update_department(client, boss, api, make_department):
    d = await make_department("QA", code="old")
    r = await client.patch(api(f"/admin/departments/{d.id}"),
                           json={"name": " QA2 ", "code": " new ", "head_name": "Босс", "is_active": False})
    assert r.status_code == 200
    assert r.json() == {"id": d.id, "name": "QA2", "code": "new", "head_name": "Босс", "is_active": False}
    db = await fresh(Department, d.id)
    assert (db.name, db.code, db.head_name, db.is_active) == ("QA2", "new", "Босс", False)


async def test_update_department_partial_and_reactivate(client, boss, api, make_department):
    d = await make_department("QA", code="c", is_active=False)
    r = await client.patch(api(f"/admin/departments/{d.id}"), json={"is_active": True})
    assert r.json()["is_active"] is True and r.json()["name"] == "QA" and r.json()["code"] == "c"
    r = await client.patch(api(f"/admin/departments/{d.id}"), json={"code": None})  # null снимает необязательное поле
    assert r.json()["code"] is None


async def test_update_department_duplicate_409_and_recovers(client, boss, api, make_department):
    await make_department("QA")
    dev = await make_department("Dev")
    r = await client.patch(api(f"/admin/departments/{dev.id}"), json={"name": "QA"})
    assert r.status_code == 409 and r.json()["detail"] == "Отдел с таким названием уже есть"
    assert (await fresh(Department, dev.id)).name == "Dev"
    assert (await client.patch(api(f"/admin/departments/{dev.id}"), json={"name": "Dev2"})).status_code == 200


async def test_update_department_404(client, boss, api):
    r = await client.patch(api("/admin/departments/999"), json={"name": "XX"})
    assert r.status_code == 404 and r.json()["detail"] == "Отдел не найден"


@pytest.mark.parametrize("body", [{"name": "A"}, {"name": "x" * 256}, {"code": "c" * 65}, {"is_active": "maybe"}])
async def test_update_department_validation_422(client, boss, api, make_department, body):
    d = await make_department("QA")
    assert (await client.patch(api(f"/admin/departments/{d.id}"), json=body)).status_code == 422


async def test_update_department_null_name_is_validation_error(client, boss, api, make_department):
    d = await make_department("QA")
    assert (await client.patch(api(f"/admin/departments/{d.id}"), json={"name": None})).status_code == 422


# ---------- Синхронизация ----------

async def test_sync_info_defaults_and_runs_limit(client, boss, api, session):
    for i in range(25):
        session.add(SyncRun(mode="mock", status="success", total=i))
    await session.commit()
    body = (await client.get(api("/admin/sync"))).json()
    assert set(body) == {"mode", "jira_url", "interval_sec", "writeback", "runs"}
    assert body["mode"] == settings.insight_mode and body["jira_url"] == settings.jira_url
    assert body["interval_sec"] == max(1, settings.insight_sync_interval_sec // 60) * 60
    assert body["writeback"] is False
    assert len(body["runs"]) == 20 and body["runs"][0]["total"] == 24  # последние 20, свежие первыми
    assert body["runs"][-1]["total"] == 5


async def test_sync_info_reflects_site_settings(client, boss, api):
    r = await client.patch(api("/admin/settings"), json={"insight_sync_interval_min": 3, "insight_writeback": True})
    assert r.status_code == 200
    body = (await client.get(api("/admin/sync"))).json()
    assert body["interval_sec"] == 180 and body["writeback"] is True and body["runs"] == []


async def test_sync_now_success(client, boss, api, session, monkeypatch):
    fake = patch_source(monkeypatch, FakeInsight([insight_obj(1, "A001"), insight_obj(2, "A002")]), "sync")
    r = await client.post(api("/admin/sync"))
    assert r.status_code == 200
    body = r.json()
    assert (body["status"], body["total"], body["created"], body["updated"], body["archived"]) == ("success", 2, 2, 0, 0)
    assert body["error"] is None and body["finished_at"] is not None and body["id"] > 0
    assert await count(Computer) == 2 and await count(SyncRun) == 1 and fake.closed
    runs = (await client.get(api("/admin/sync"))).json()["runs"]
    assert [x["id"] for x in runs] == [body["id"]]


async def test_sync_now_second_run_updates(client, boss, api, monkeypatch):
    patch_source(monkeypatch, FakeInsight([insight_obj(1, "A001")]), "sync")
    await client.post(api("/admin/sync"))
    patch_source(monkeypatch, FakeInsight([insight_obj(1, "A001", **{"ОЗУ": "16 GB"})]), "sync")
    body = (await client.post(api("/admin/sync"))).json()
    assert body["status"] == "success" and (body["created"], body["updated"], body["total"]) == (0, 1, 1)
    assert await count(SyncRun) == 2


async def test_sync_now_insight_failure_is_200_with_failed_run(client, boss, api, monkeypatch):
    patch_source(monkeypatch, FakeInsight(fetch_error=RuntimeError("Insight недоступен")), "sync")
    r = await client.post(api("/admin/sync"))
    assert r.status_code == 200
    assert r.json()["status"] == "failed" and "Insight недоступен" in r.json()["error"]
    assert await count(Computer) == 0


async def test_sync_now_conflict_when_already_running(client, boss, api, monkeypatch):
    from app.services.sync import SYNC_LOCK_KEY
    patch_source(monkeypatch, FakeInsight([insight_obj(1, "A001")]), "sync")
    async with SessionLocal() as other:  # другой процесс держит advisory-lock
        await other.execute(select(func.pg_advisory_xact_lock(SYNC_LOCK_KEY)))
        r = await client.post(api("/admin/sync"))
        await other.rollback()
    assert r.status_code == 409 and "уже выполняется" in r.json()["detail"]
    assert await count(Computer) == 0
    assert (await client.post(api("/admin/sync"))).status_code == 200  # замок снят — снова можно



async def test_update_pool_null_is_published_is_validation_error(client, boss, api, make_pool):
    pool = await make_pool("Main")
    assert (await client.patch(api(f"/admin/pools/{pool.id}"), json={"is_published": None})).status_code == 422


async def test_update_department_null_is_active_is_validation_error(client, boss, api, make_department):
    d = await make_department("QA")
    assert (await client.patch(api(f"/admin/departments/{d.id}"), json={"is_active": None})).status_code == 422
