"""Каталог (видимость по пулам/отделам, фильтры, счётчики), бронирование и возврат через HTTP."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import Computer, ComputerStatus, ServiceRequest, Tier, UserRole
from app.services import bookings as bookings_service
from app.services import service_requests

from .test_service_requests import FakeSd

ADMIN = UserRole.admin.value


@pytest.fixture
async def world(make_department, make_pool, make_computer):
    """Отделы qa/dev; пулы: открытый, только QA, только Dev, неопубликованный; ПК во всех + без пула + архивный."""
    qa, dev = await make_department("QA"), await make_department("Dev")
    open_pool = await make_pool("Open")
    qa_pool = await make_pool("QaOnly", departments=[qa])
    dev_pool = await make_pool("DevOnly", departments=[dev])
    hidden_pool = await make_pool("Draft", is_published=False)
    c = {
        "open": await make_computer("A-open", open_pool),
        "qa": await make_computer("A-qa", qa_pool),
        "dev": await make_computer("A-dev", dev_pool),
        "draft": await make_computer("A-draft", hidden_pool),
        "nopool": await make_computer("A-nopool"),
        "archived": await make_computer("A-arch", open_pool, is_archived=True),
    }
    return {"qa": qa, "dev": dev, "pools": [open_pool, qa_pool, dev_pool, hidden_pool], "c": c}


async def _names(client, api, **params):
    r = await client.get(api("/computers"), params=params)
    assert r.status_code == 200, r.text
    return [x["name"] for x in r.json()]


# ---------- Видимость ----------

async def test_employee_sees_open_pool_and_own_department_only(client, login, make_user, world, api):
    login(await make_user("emp", department=world["qa"]))
    assert await _names(client, api) == ["A-open", "A-qa"]


async def test_employee_without_department_sees_only_open_pools(client, login, make_user, world, api):
    login(await make_user("emp"))
    assert await _names(client, api) == ["A-open"]


async def test_admin_sees_all_published_pools_but_not_pool_less_or_archived(client, login, make_user, world, api):
    login(await make_user("boss", role=ADMIN))
    assert await _names(client, api) == ["A-dev", "A-open", "A-qa"]  # без черновика, без-пула и архивных


async def test_pool_unpublish_hides_computers(client, login, make_user, world, session, api):
    login(await make_user("emp", department=world["qa"]))
    world["pools"][0].is_published = False
    await session.commit()
    assert await _names(client, api) == ["A-qa"]


@pytest.mark.parametrize("key,code", [("open", 200), ("qa", 200), ("dev", 404), ("draft", 404), ("nopool", 404),
                                      ("archived", 404)])
async def test_computer_card_visibility_for_employee(client, login, make_user, world, api, key, code):
    login(await make_user("emp", department=world["qa"]))
    assert (await client.get(api(f"/computers/{world['c'][key].id}"))).status_code == code


async def test_computer_card_admin_and_missing(client, login, make_user, world, api):
    login(await make_user("boss", role=ADMIN))
    assert (await client.get(api(f"/computers/{world['c']['dev'].id}"))).status_code == 200
    assert (await client.get(api(f"/computers/{world['c']['archived'].id}"))).status_code == 404
    assert (await client.get(api("/computers/99999"))).status_code == 404


async def test_attributes_hidden_from_employee_but_not_admin(client, login, make_user, make_pool, make_computer, api):
    comp = await make_computer("A1", await make_pool("P"), attributes={"Secret": "x"})
    login(await make_user("emp"))
    assert (await client.get(api(f"/computers/{comp.id}"))).json()["attributes"] == {}
    client.cookies.clear()
    login(await make_user("boss", role=ADMIN))
    assert (await client.get(api(f"/computers/{comp.id}"))).json()["attributes"] == {"Secret": "x"}


# ---------- Фильтры, поиск, сортировка ----------

@pytest.fixture
async def fleet(make_pool, make_computer, make_user, login):
    pool = await make_pool("Fleet")
    mk = lambda *a, **k: make_computer(*a, pool=pool, **k)  # noqa: E731
    await mk("A9", ram_gb=16, tier="medium", cpu="Ryzen 5", location="Floor 1")
    await mk("A10", ram_gb=64, tier="powerful", gpu="RTX 4090", hostname="beast-host")
    await mk("A150", ram_gb=8, tier="weak", status=ComputerStatus.booked.value)
    await mk("A2", ram_gb=32, tier="powerful", status=ComputerStatus.maintenance.value)
    await mk("vm-1", ram_gb=2, tier="vm", is_virtual=True)
    await mk("Z-noram", ram_gb=None, tier="medium")
    await mk("tiny", ram_gb=4, tier="weak")  # слабее порога RAM_FLOOR — в каталог не попадает
    login(await make_user("emp"))


async def test_default_list_only_available_natural_sorted_and_ram_floor(client, fleet, api):
    # занятые/в резерве скрыты, «слабее 8 ГБ» скрыт, но ВМ с 2 ГБ и ПК с неизвестной ОЗУ видны; A9 < A10 (натуральный порядок)
    assert await _names(client, api) == ["A9", "A10", "vm-1", "Z-noram"]


async def test_only_available_false_shows_booked_and_reserved(client, fleet, api):
    assert await _names(client, api, only_available="false") == ["A2", "A9", "A10", "A150", "vm-1", "Z-noram"]


@pytest.mark.parametrize("params,expected", [
    ({"tier": "powerful"}, ["A10"]),
    ({"tier": "powerful", "only_available": "false"}, ["A2", "A10"]),
    ({"tier": "vm"}, ["vm-1"]),
    ({"min_ram": 16}, ["A9", "A10"]),
    ({"gpu_only": "true"}, ["A10"]),
    ({"q": "rtx"}, ["A10"]),
    ({"q": "BEAST"}, ["A10"]),          # hostname, регистр не важен
    ({"q": "ryzen"}, ["A9"]),           # cpu
    ({"q": "floor 1"}, ["A9"]),         # location
    ({"q": "  a9  "}, ["A9"]),          # пробелы по краям обрезаются
    ({"q": "nothing-like-this"}, []),
    ({"q": "ram", "tier": "medium"}, ["Z-noram"]),
    ({"sort": "ram_desc"}, ["A10", "A9", "vm-1", "Z-noram"]),
    ({"sort": "ram_asc"}, ["Z-noram", "vm-1", "A9", "A10"]),  # None считается как 0
])
async def test_list_filters(client, fleet, api, params, expected):
    assert await _names(client, api, **params) == expected


@pytest.mark.parametrize("params", [{"tier": "mega"}, {"sort": "random"}, {"min_ram": "lots"}])
async def test_list_rejects_invalid_params(client, fleet, api, params):
    assert (await client.get(api("/computers"), params=params)).status_code == 422


async def test_summary_counts_per_tier(client, fleet, api):
    r = await client.get(api("/catalog/summary"))
    assert r.status_code == 200
    got = {x["tier"]: x for x in r.json()}
    assert list(got) == [t.value for t in Tier]  # все категории присутствуют всегда
    # powerful: A10 свободен, A2 в резерве -> available=1, total=2; min/max ОЗУ только по свободным
    assert got["powerful"] == {"tier": "powerful", "available": 1, "total": 2, "min_ram_gb": 64, "max_ram_gb": 64}
    assert got["medium"]["available"] == 2 and got["medium"]["total"] == 2 and got["medium"]["min_ram_gb"] == 16
    assert (got["weak"]["available"], got["weak"]["total"]) == (0, 1)  # A150 занят; tiny отсечён порогом ОЗУ
    assert got["weak"]["min_ram_gb"] is None
    assert (got["vm"]["available"], got["vm"]["total"]) == (1, 1)


async def test_summary_respects_visibility(client, login, make_user, world, api):
    login(await make_user("emp", department=world["dev"]))
    got = {x["tier"]: x for x in (await client.get(api("/catalog/summary"))).json()}
    assert sum(x["total"] for x in got.values()) == 2  # A-open + A-dev; архив, чужой отдел, черновик и без-пула не считаются
    assert all(x["available"] == x["total"] for x in got.values())


async def test_summary_empty(client, login, make_user, api):
    login(await make_user("emp"))
    got = (await client.get(api("/catalog/summary"))).json()
    assert [(x["available"], x["total"]) for x in got] == [(0, 0)] * 4


async def test_departments_only_active_sorted(client, login, make_user, make_department, api):
    await make_department("Zeta")
    await make_department("Alpha")
    await make_department("Old", is_active=False)
    login(await make_user("emp"))
    assert [d["name"] for d in (await client.get(api("/departments"))).json()] == ["Alpha", "Zeta"]


# ---------- Бронирование ----------

def _payload(comp, dept, **kw):
    return {"computer_id": comp.id, "department_id": dept.id,
            "requester_nick": "ivanov", "expected_return_at": clock.today().isoformat(), **kw}


@pytest.fixture
async def shop(make_department, make_pool, make_computer, make_user, login):
    """Сотрудник emp (отдел QA) + свободный ПК в открытом пуле."""
    dept = await make_department("QA")
    pool = await make_pool("Open")
    comp = await make_computer("A1", pool, insight_status="Свободен")  # статус Insight решает, чем станет ПК после возврата
    emp = await make_user("emp", department=dept)
    login(emp)
    return {"dept": dept, "comp": comp, "emp": emp, "pool": pool}


async def test_create_booking_ok(client, shop, session, api):
    tomorrow = clock.today() + timedelta(days=1)
    r = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"], purpose=" тест ",
                                                          expected_return_at=tomorrow.isoformat()))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order_number"] == 1 and body["status"] == "active" and body["purpose"] == "тест"
    assert body["computer"]["name"] == "A1" and body["department"]["name"] == "QA"
    assert body["user"]["id"] == shop["emp"].id and body["expected_return_at"] == tomorrow.isoformat()
    comp = await session.scalar(select(Computer).where(Computer.id == shop["comp"].id).execution_options(populate_existing=True))
    assert comp.status == ComputerStatus.booked and comp.department_id == shop["dept"].id and comp.order_number == 1
    assert await _names(client, api) == []  # из каталога свободных пропал
    assert await _names(client, api, only_available="false") == ["A1"]


async def test_order_numbers_are_sequential(client, shop, make_computer, api):
    second = await make_computer("A2", shop["pool"])
    first = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))
    nxt = await client.post(api("/bookings"), json=_payload(second, shop["dept"]))
    assert (first.json()["order_number"], nxt.json()["order_number"]) == (1, 2)


async def test_double_booking_conflict(client, shop, login, make_user, api):
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).status_code == 201
    r = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))
    assert r.status_code == 409 and "A1" in r.json()["detail"]
    client.cookies.clear()
    login(await make_user("other"))  # другой сотрудник тоже получает 409
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).status_code == 409


@pytest.mark.parametrize("status", [ComputerStatus.maintenance, ComputerStatus.in_use, ComputerStatus.retired,
                                    ComputerStatus.unknown])
async def test_booking_non_available_is_409(client, shop, session, api, status):
    shop["comp"].status = status.value
    await session.commit()
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).status_code == 409


async def test_booking_invisible_computers_are_404(client, shop, make_computer, make_pool, make_department, session, api):
    other = await make_department("Other")
    cases = [
        await make_computer("X-nopool"),
        await make_computer("X-foreign", await make_pool("Foreign", departments=[other])),
        await make_computer("X-draft", await make_pool("Draft", is_published=False)),
        await make_computer("X-arch", shop["pool"], is_archived=True),
    ]
    for comp in cases:
        r = await client.post(api("/bookings"), json=_payload(comp, shop["dept"]))
        assert r.status_code == 404, comp.name
    assert (await client.post(api("/bookings"), json={**_payload(shop["comp"], shop["dept"]), "computer_id": 999})
            ).status_code == 404


async def test_admin_booking_for_unknown_or_inactive_department_is_404(client, shop, make_department, make_user,
                                                                     login, api):
    off = await make_department("Off", is_active=False)
    login(await make_user("boss", role=ADMIN))
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], off))).status_code == 404
    assert (await client.post(api("/bookings"), json={**_payload(shop["comp"], off), "department_id": 999})
            ).status_code == 404


async def test_user_booking_for_foreign_department_is_403_and_without_department_409(client, shop, make_department,
                                                                                     make_user, login, api):
    other = await make_department("Other")
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], other))).status_code == 403
    login(await make_user("loner"))
    r = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))
    assert r.status_code == 409 and "не назначен отдел" in r.json()["detail"]


async def test_booking_requester_name_is_profile_name_not_body(client, shop, api):
    r = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]) | {"requester_name": "Самозванец"})
    assert r.status_code == 201 and r.json()["requester_name"] == "emp"  # display_name сотрудника


async def test_booking_without_department_in_body_uses_own(client, shop, api):
    body = {k: v for k, v in _payload(shop["comp"], shop["dept"]).items() if k != "department_id"}
    r = await client.post(api("/bookings"), json=body)
    assert r.status_code == 201 and r.json()["department"]["id"] == shop["dept"].id


@pytest.mark.parametrize("patch", [
    {"requester_nick": ""}, {"purpose": "x" * 2001},
    {"requester_nick": "   "},  # одни пробелы — это пустое значение
    {"expected_return_at": (clock.today() - timedelta(days=1)).isoformat()}, {"expected_return_at": "not-a-date"},
    {"expected_return_at": None}, {"expected_return_at": ""},  # срок возврата обязателен
])
async def test_booking_validation_422(client, shop, api, patch):
    assert (await client.post(api("/bookings"), json={**_payload(shop["comp"], shop["dept"]), **patch})
            ).status_code == 422


async def test_booking_requires_all_fields(client, shop, api):
    assert (await client.post(api("/bookings"), json={"computer_id": shop["comp"].id})).status_code == 422


async def test_booking_without_return_date_is_422(client, shop, api):
    body = _payload(shop["comp"], shop["dept"])
    del body["expected_return_at"]
    r = await client.post(api("/bookings"), json=body)
    assert r.status_code == 422 and "expected_return_at" in r.text


async def test_admin_can_book_any_pool(client, login, make_user, shop, make_pool, make_computer, make_department, api):
    """Админ видит пулы чужих отделов, значит может бронировать из них."""
    dev = await make_department("Dev")
    comp = await make_computer("D1", await make_pool("DevOnly", departments=[dev]))
    client.cookies.clear()
    login(await make_user("boss", role=ADMIN))
    assert (await client.post(api("/bookings"), json=_payload(comp, dev))).status_code == 201


# ---------- Мои бронирования и возврат ----------

async def test_my_bookings_only_own_newest_first(client, shop, login, make_user, make_computer, make_department, api):
    c2 = await make_computer("A2", shop["pool"])
    c3 = await make_computer("A3", shop["pool"])
    await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))
    await client.post(api("/bookings"), json=_payload(c2, shop["dept"]))
    client.cookies.clear()
    ops = await make_department("Ops")
    login(await make_user("other", department=ops))
    await client.post(api("/bookings"), json=_payload(c3, ops))
    assert [b["computer"]["name"] for b in (await client.get(api("/bookings/my"))).json()] == ["A3"]
    client.cookies.clear()
    login(shop["emp"])
    assert [b["computer"]["name"] for b in (await client.get(api("/bookings/my"))).json()] == ["A2", "A1"]


async def test_team_sees_and_manages_booking_of_teammate(client, shop, login, make_user, make_department, api):
    """Участник команды видит бронь коллеги в «моих», продлевает и возвращает её; чужая команда получает 403."""
    booking = (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).json()
    new_date = (clock.today() + timedelta(days=5)).isoformat()
    client.cookies.clear()

    login(await make_user("outsider", department=await make_department("Ops")))
    assert (await client.get(api("/bookings/my"))).json() == []
    assert (await client.post(api(f"/bookings/{booking['id']}/extend"), json={"expected_return_at": new_date})).status_code == 403
    assert (await client.post(api(f"/bookings/{booking['id']}/return"), json={})).status_code == 403
    client.cookies.clear()

    login(await make_user("mate", department=shop["dept"]))
    mine = (await client.get(api("/bookings/my"))).json()
    assert [(b["id"], b["user"]["username"]) for b in mine] == [(booking["id"], "emp")]
    r = await client.post(api(f"/bookings/{booking['id']}/extend"), json={"expected_return_at": new_date})
    assert r.status_code == 200 and r.json()["expected_return_at"] == new_date
    r = await client.post(api(f"/bookings/{booking['id']}/return"), json={})
    assert r.status_code == 200 and r.json()["returned_by"]["username"] == "mate"


async def test_my_bookings_empty(client, shop, api):
    r = await client.get(api("/bookings/my"))
    assert r.status_code == 200 and r.json() == []


async def _book(client, api, shop):
    r = await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))
    return r.json()["id"]


async def test_return_by_owner(client, shop, session, api, make_user, login):
    bid = await _book(client, api, shop)
    r = await client.post(api(f"/bookings/{bid}/return"), json={"comment": " всё ок "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "returned" and body["return_comment"] == "всё ок"
    assert body["returned_at"] and body["returned_by"]["id"] == shop["emp"].id
    comp = await session.scalar(select(Computer).where(Computer.id == shop["comp"].id).execution_options(populate_existing=True))
    assert comp.status == ComputerStatus.cleaning and comp.department_id is None and comp.order_number is None
    assert await _names(client, api) == []  # пока ПК на очистке, в каталоге его нет
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).status_code == 409

    worker = await make_user("worker", role=UserRole.executor.value)
    login(worker)
    assert (await client.post(api(f"/executor/returns/{bid}/cleaned"))).status_code == 200  # исполнитель очистил диск
    login(shop["emp"])
    assert await _names(client, api) == ["A1"]  # снова в каталоге
    assert (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).status_code == 201


@pytest.mark.parametrize("task_status, cancelled", [("Backlog", True), ("Решено", False)])
async def test_return_request_is_created_only_for_issued_pc(client, shop, api, monkeypatch, task_status, cancelled):
    """Отмена заказа до подготовки не создаёт заявку «Возврат ПК»: ПК не выдавали."""
    for k, v in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="").items():
        monkeypatch.setattr(settings, k, v)
    fake = FakeSd()
    fake.status = real_sd.SdStatus(task_status, "new" if cancelled else "done")
    monkeypatch.setattr(service_requests, "sd", fake)
    created = AsyncMock()
    monkeypatch.setattr(bookings_service, "create_return_request", created)
    monkeypatch.setattr(bookings_service, "create_prepare_request", AsyncMock())
    bid = await _book(client, api, shop)
    async with SessionLocal() as s:
        s.add(ServiceRequest(kind="prepare", user_id=shop["emp"].id, booking_id=bid, issue_key="DR-7", summary="s",
                             description="d", status=task_status))
        await s.commit()
    r = await client.post(api(f"/bookings/{bid}/return"), json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == ("cancelled" if cancelled else "returned")
    assert created.await_count == (0 if cancelled else 1)


async def test_return_of_taken_order_is_conflict(client, shop, api, monkeypatch):
    for k, v in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="").items():
        monkeypatch.setattr(settings, k, v)
    fake = FakeSd()
    fake.status = real_sd.SdStatus("In Progress", "indeterminate")
    monkeypatch.setattr(service_requests, "sd", fake)
    monkeypatch.setattr(bookings_service, "create_prepare_request", AsyncMock())
    bid = await _book(client, api, shop)
    async with SessionLocal() as s:
        s.add(ServiceRequest(kind="prepare", user_id=shop["emp"].id, booking_id=bid, issue_key="DR-7", summary="s",
                             description="d", status="Backlog"))
        await s.commit()
    r = await client.post(api(f"/bookings/{bid}/return"), json={})
    assert r.status_code == 409 and "Исполнитель уже взял заказ" in r.json()["detail"]


async def test_return_without_body_fields(client, shop, api):
    bid = await _book(client, api, shop)
    assert (await client.post(api(f"/bookings/{bid}/return"), json={})).status_code == 200


async def test_return_twice_is_409(client, shop, api):
    bid = await _book(client, api, shop)
    await client.post(api(f"/bookings/{bid}/return"), json={})
    assert (await client.post(api(f"/bookings/{bid}/return"), json={})).status_code == 409


async def test_return_unknown_booking_is_404(client, shop, api):
    assert (await client.post(api("/bookings/999/return"), json={})).status_code == 404


async def test_return_by_stranger_is_403_admin_can(client, shop, login, make_user, session, api):
    bid = await _book(client, api, shop)
    client.cookies.clear()
    login(await make_user("stranger"))
    assert (await client.post(api(f"/bookings/{bid}/return"), json={})).status_code == 403
    client.cookies.clear()
    login(await make_user("boss", role=ADMIN))
    r = await client.post(api(f"/bookings/{bid}/return"), json={"comment": "забрали"})
    assert r.status_code == 200 and r.json()["returned_by"]["username"] == "boss"


# ---------- продление ----------

async def test_extend_booking_via_api(client, shop, api):
    booking = (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).json()
    new = (clock.today() + timedelta(days=5)).isoformat()
    r = await client.post(api(f"/bookings/{booking['id']}/extend"), json={"expected_return_at": new, "comment": "тесты"})
    assert r.status_code == 200, r.text
    assert r.json()["expected_return_at"] == new
    mine = (await client.get(api("/bookings/my"))).json()
    assert mine[0]["expected_return_at"] == new


@pytest.mark.parametrize("body", [
    {}, {"expected_return_at": None}, {"expected_return_at": ""},
    {"expected_return_at": (clock.today() - timedelta(days=1)).isoformat()},
    {"expected_return_at": (clock.today() + timedelta(days=1)).isoformat(), "comment": "x" * 2001},
])
async def test_extend_validation_422(client, shop, api, body):
    booking = (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).json()
    assert (await client.post(api(f"/bookings/{booking['id']}/extend"), json=body)).status_code == 422


async def test_extend_not_later_is_409_and_foreign_is_403(client, shop, api, login, make_user):
    booking = (await client.post(api("/bookings"), json=_payload(shop["comp"], shop["dept"]))).json()
    url = api(f"/bookings/{booking['id']}/extend")
    same = {"expected_return_at": booking["expected_return_at"]}
    r = await client.post(url, json=same)
    assert r.status_code == 409 and "позже текущего" in r.json()["detail"]
    client.cookies.clear()
    login(await make_user("other"))
    later = {"expected_return_at": (clock.today() + timedelta(days=1)).isoformat()}
    assert (await client.post(url, json=later)).status_code == 403
