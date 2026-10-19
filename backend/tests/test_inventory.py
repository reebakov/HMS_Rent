"""Инвентаризация (services/inventory.py): сводка парка, фильтры, расхождения, CSV-выгрузка."""
import csv
import io
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import clock
from app.services import inventory, runtime
from app.services.inventory import _safe_cell
from tests.sync_fakes import add_booking

TODAY = clock.today()


async def names(session, **kw) -> list[str]:
    rows, _ = await inventory.list_inventory(session, **kw)
    return [r.name for r in rows]


@pytest.fixture
async def fleet(make_computer, make_pool, make_department):
    """Небольшой парк: свободные, занятые, недоступные, архивный."""
    dept, pool = await make_department("QA"), await make_pool("Main")
    c = {}
    c["free1"] = await make_computer("A1", tier="weak", pool=pool, hostname="OFC-A1", serial_number="SN-111",
                                     ip_address="10.0.0.1", cpu="Intel i3", insight_key="ITAM-1")
    c["free2"] = await make_computer("A10", tier="medium", gpu="GTX 1050")
    c["booked"] = await make_computer("A2", status="booked", tier="powerful", pool=pool, department_id=dept.id)
    c["maint"] = await make_computer("A3", status="maintenance")
    c["in_use"] = await make_computer("A4", status="in_use")
    c["retired"] = await make_computer("A5", status="retired")
    c["unknown"] = await make_computer("A6", status="unknown")
    c["archived"] = await make_computer("A7", is_archived=True)
    c["dept"], c["pool"] = dept, pool
    return c


# ---------- фильтры и порядок ----------

async def test_default_excludes_archived_and_sorts_naturally(session, fleet):
    assert await names(session) == ["A1", "A2", "A3", "A4", "A5", "A6", "A10"]  # A10 после A6, а не после A1
    assert "A7" in await names(session, include_archived=True)


async def test_status_filter_and_unavailable_group(session, fleet):
    assert await names(session, status="available") == ["A1", "A10"]
    assert await names(session, status="booked") == ["A2"]
    # «недоступно» = резерв + занят в Insight + списан + неизвестно
    assert await names(session, status="unavailable") == ["A3", "A4", "A5", "A6"]


async def test_tier_department_pool_filters(session, fleet):
    assert await names(session, tier="powerful") == ["A2"]
    assert await names(session, department_id=fleet["dept"].id) == ["A2"]
    assert await names(session, pool_id=str(fleet["pool"].id)) == ["A1", "A2"]
    assert "A1" not in await names(session, pool_id="none") and "A10" in await names(session, pool_id="none")


async def test_search_is_case_insensitive_over_many_fields(session, fleet):
    for q in ("a10", "ofc-a1", "sn-111", "10.0.0.1", "intel", "gtx", "itam-1"):
        assert await names(session, q=q), q
    assert await names(session, q="  sn-111 ") == ["A1"]
    assert await names(session, q="нет такого") == []


async def test_pagination_and_total(session, fleet):
    rows, total = await inventory.list_inventory(session, limit=3, offset=2)
    assert total == 7 and [r.name for r in rows] == ["A3", "A4", "A5"]
    rows, total = await inventory.list_inventory(session, limit=None)
    assert len(rows) == total == 7


# ---------- расхождения ----------

async def test_issues_detected(session, fleet, make_computer, make_user, make_department):
    user, dept = await make_user("ivanov"), fleet["dept"]
    await runtime.update(session, {"insight_writeback": True})

    async def booked(name, **kw):
        comp = await make_computer(name, status="booked", **kw)
        await add_booking(session, comp, user, dept, expected_return_at=kw.pop("until", None))
        return comp

    await booked("B1", is_archived=True)
    await booked("B2", insight_status="Резерв")
    await booked("B3", insight_status="Списан")
    await booked("B4", insight_status="Свободен")
    await booked("B5", insight_status="Свободен", writeback_pending=True)  # запись ещё не ушла — не расхождение
    await booked("B6", insight_status="В использовании")  # всё в порядке
    over = await make_computer("B7", status="booked", insight_status="В использовании")
    await add_booking(session, over, user, dept, expected_return_at=TODAY - timedelta(days=1))
    ok_date = await make_computer("B8", status="booked", insight_status="В использовании")
    await add_booking(session, ok_date, user, dept, expected_return_at=TODAY)  # сегодня — ещё не просрочка
    await make_computer("B9", writeback_error="Insight 500")

    rows, total = await inventory.list_inventory(session, issues_only=True, include_archived=True)
    by_name = {r.name: r.issues for r in rows}
    assert set(by_name) == {"B1", "B2", "B3", "B4", "B7", "B9"} and total == 6
    assert "пропал из Insight" in by_name["B1"][0]
    assert "«Резерв»" in by_name["B2"][0] and "«Списан»" in by_name["B3"][0]
    assert "числится свободным" in by_name["B4"][0]
    assert f"{TODAY - timedelta(days=1):%d.%m.%Y}" in by_name["B7"][0] and "Просрочен" in by_name["B7"][0]
    assert "Insight 500" in by_name["B9"][0]


async def test_free_in_insight_issue_only_with_writeback(session, make_computer, make_user, make_department):
    comp = await make_computer("B1", status="booked", insight_status="Свободен")
    await add_booking(session, comp, await make_user("u"), await make_department("QA"))
    assert await names(session, issues_only=True) == []  # запись выключена — Insight и не должен знать о брони
    await runtime.update(session, {"insight_writeback": True})
    assert await names(session, issues_only=True) == ["B1"]


async def test_issues_pagination(session, make_computer):
    for i in range(3):
        await make_computer(f"E{i}", writeback_error="err")
    rows, total = await inventory.list_inventory(session, issues_only=True, limit=2, offset=1)
    assert total == 3 and len(rows) == 2


# ---------- сводка ----------

async def test_stats(session, fleet, make_user):
    user = await make_user("ivanov")
    await add_booking(session, fleet["booked"], user, fleet["dept"], expected_return_at=TODAY - timedelta(days=2))
    stats = await inventory.get_stats(session)
    assert stats.total == 7  # архивный не считается
    assert stats.by_status == {"available": 2, "booked": 1, "maintenance": 1, "in_use": 1, "retired": 1,
                               "unknown": 1}
    tiers = {t.tier: t for t in stats.by_tier}
    assert set(tiers) == {"weak", "medium", "powerful", "vm"}
    assert (tiers["weak"].total, tiers["weak"].available) == (1, 1)
    assert (tiers["powerful"].booked, tiers["vm"].total) == (1, 0)
    assert tiers["medium"].total == 5  # A10 + 4 недоступных с tier по умолчанию
    assert (stats.active_bookings, stats.departments_using, stats.overdue) == (1, 1, 1)
    assert stats.in_pools == 2 and stats.issues == 1 and stats.last_sync is None


async def test_stats_empty_fleet(session):
    stats = await inventory.get_stats(session)
    assert stats.total == 0 and stats.active_bookings == 0 and stats.overdue == 0 and len(stats.by_tier) == 4


# ---------- CSV ----------

async def csv_rows(session, **kw) -> tuple[str, list[list[str]]]:
    rows, _ = await inventory.list_inventory(session, limit=None, **kw)
    text = inventory.inventory_csv(rows)
    return text, list(csv.reader(io.StringIO(text.lstrip("﻿")), delimiter=";"))


async def test_csv_excel_format_and_cyrillic(session, make_computer, make_pool, make_department, make_user):
    comp = await make_computer("Ж-01", status="booked", tier="powerful", cpu="Intel", ram_gb=32,
                               pool=await make_pool("Основной"), usage_until=date(2030, 5, 17), order_number=7,
                               insight_status="В использовании", insight_key="ITAM-9")
    dept = await make_department("Тестирование (QA)")
    comp.department_id = dept.id
    await session.commit()
    await add_booking(session, comp, await make_user("u"), dept, requester_name="Пётр Петров", requester_nick="petya",
                      booked_at=datetime(2026, 1, 15, 21, 30, tzinfo=timezone.utc))
    text, rows = await csv_rows(session)
    assert text.startswith("﻿") and text.split("\n")[0].count(";") == 19  # BOM + разделитель «;»
    header, row = rows[0], rows[1]
    assert len(rows) == 2 and len(row) == len(header) == 20
    data = dict(zip(header, row, strict=True))
    assert data["ПК"] == "Ж-01" and data["Категория"] == "Мощный" and data["Статус портала"] == "Забронирован"
    assert data["Пул выдачи"] == "Основной" and data["Команда-получатель"] == "Тестирование (QA)"
    assert data["Забронировал"] == "Пётр Петров" and data["Ник"] == "petya"
    assert data["С даты"] == "16.01.2026 00:30"  # время в часовом поясе портала (Europe/Moscow)
    assert data["Срок использования"] == "17.05.2030" and data["Номер заказа"] == "7" and data["ОЗУ, ГБ"] == "32"


async def test_csv_escapes_special_characters(session, make_computer, make_user, make_department):
    nasty = 'Имя "в кавычках", с запятой; точкой с запятой\nи переводом строки'
    comp = await make_computer("A1", status="booked", location=nasty, os="a,b", gpu='say "hi"')
    await add_booking(session, comp, await make_user("u"), await make_department("QA"), requester_name=nasty)
    text, rows = await csv_rows(session)
    assert len(rows) == 2 and len(rows[1]) == 20  # перенос строки внутри поля не ломает структуру
    data = dict(zip(rows[0], rows[1], strict=True))
    assert data["Расположение"] == nasty and data["Забронировал"] == nasty
    assert data["ОС"] == "a,b" and data["Видеокарта"] == 'say "hi"'
    assert '"say ""hi"""' in text  # кавычки удвоены по RFC 4180


async def test_csv_empty_values_and_unknown_labels(session, make_computer):
    await make_computer("A1", status="maintenance", tier="vm")
    _, rows = await csv_rows(session)
    data = dict(zip(rows[0], rows[1], strict=True))
    assert data["Статус портала"] == "Резерв" and data["Категория"] == "Виртуальная"
    assert data["ОЗУ, ГБ"] == "" and data["Забронировал"] == "" and data["С даты"] == ""


async def test_csv_issues_joined(session, make_computer):
    await make_computer("A1", writeback_error="err")
    _, rows = await csv_rows(session)
    assert "Ошибка записи в Insight: err" in dict(zip(rows[0], rows[1], strict=True))["Расхождения"]


async def test_csv_empty_fleet_has_only_header(session):
    _, rows = await csv_rows(session)
    assert len(rows) == 1


async def test_csv_formula_injection(session, make_computer, make_user, make_department):
    """Ячейки, похожие на формулу, экранируются префиксом «'» — Excel не выполнит их."""
    evil = '=HYPERLINK("http://evil.example","click")'
    comp = await make_computer("A1", status="booked", serial_number="+1-2-3")
    await add_booking(session, comp, await make_user("u"), await make_department("QA"), requester_name=evil)
    _, rows = await csv_rows(session)
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["Забронировал"] == "'" + evil
    assert row["Серийный номер"] == "'+1-2-3"
    assert not any(cell[:1] in ("=", "+", "-", "@") for cell in rows[1] if cell)


@pytest.mark.parametrize("raw", ["=1+1", "+7", "-2", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_safe_cell_escapes_formula_prefixes(raw):
    assert _safe_cell(raw) == "'" + raw


@pytest.mark.parametrize("raw", ["A1", "", "Иванов", "5 ГБ", 16, None])
def test_safe_cell_keeps_normal_values(raw):
    assert _safe_cell(raw) == raw


async def test_export_endpoint(client, login, api, make_user, make_computer, make_pool):
    pool = await make_pool("Main")
    await make_computer("A1", pool=pool)
    await make_computer("A2")
    admin = await make_user("boss", role="admin")
    login(admin)
    r = await client.get(api("/admin/inventory/export"))
    assert r.status_code == 200 and r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="inventory_{TODAY:%Y-%m-%d}.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf")  # BOM для Excel
    assert r.text.count("\n") >= 3
    r = await client.get(api("/admin/inventory/export"), params={"pool_id": str(pool.id)})
    assert "A1" in r.text and "A2" not in r.text


async def test_export_requires_admin(client, login, api, make_user):
    assert (await client.get(api("/admin/inventory/export"))).status_code == 401
    login(await make_user("ivanov"))
    assert (await client.get(api("/admin/inventory/export"))).status_code == 403
    assert (await client.get(api("/admin/inventory"))).status_code == 403
