"""Маршруты /requests (заявки в Service Desk) и заявка «Возврат» при возврате ПК через /bookings/{id}/return."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core import clock
from app.core.config import settings
from app.integrations import servicedesk as real_sd
from app.models import UserRole, VirtualMachine
from app.schemas.service_request import earliest_wanted_by
from app.schemas.settings import default_pc_builds, default_pc_os
from app.services import runtime

from .sync_fakes import add_booking
from .test_service_requests import FakeSd, add_req, boom, fresh, rows


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSd()
    monkeypatch.setattr("app.services.service_requests.sd", fake)
    for k, v in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="", sd_password="",
                     sd_service_desk_id=54, sd_return_on_return=True).items():
        monkeypatch.setattr(settings, k, v)
    return fake


@pytest_asyncio.fixture
async def env(session, make_department, make_user, make_pool, make_computer):
    qa, ops = await make_department("QA"), await make_department("Ops")
    owner = await make_user("owner", department=qa, display_name="Иван Иванов")
    mate = await make_user("mate", department=qa)
    stranger = await make_user("stranger", department=ops)
    admin = await make_user("admin", role=UserRole.admin.value)
    comp = await make_computer("A001", await make_pool(), insight_status="Свободен")
    booking = await add_booking(session, comp, owner, qa)
    vm = VirtualMachine(name="A1007", cpu=2, ram_gb=4, disk_gb=50, status="ready", order_number=77,
                        user_id=owner.id, department_id=qa.id, requester_name="Иван", requester_nick="ivan", attrs={})
    session.add(vm)
    await session.commit()
    return SimpleNamespace(qa=qa, owner=owner, mate=mate, stranger=stranger, admin=admin, comp=comp,
                           booking=booking, vm=vm)


# ---------- вход и конфиг ----------

@pytest.mark.parametrize("method, path, body", [
    ("get", "/requests/config", None), ("get", "/requests/my", None), ("post", "/requests", {"vm_id": 1, "message": "Проблема"}),
    ("get", "/requests/1", None), ("post", "/requests/1/comments", {"message": "ok"}),
])
async def test_anonymous_gets_401(client, api, method, path, body):
    r = await (client.get(api(path)) if method == "get" else client.post(api(path), json=body))
    assert r.status_code == 401


@pytest.mark.parametrize("token, enabled", [("tok", True), ("", False)])
async def test_config_enabled(client, login, api, env, sd, monkeypatch, token, enabled):
    monkeypatch.setattr(settings, "sd_token", token)
    login(env.owner)
    r = await client.get(api("/requests/config"))
    assert r.status_code == 200 and r.json() == {"enabled": enabled}


# ---------- GET /requests/my ----------

async def test_my_requests_with_portal_url(client, login, api, session, env, sd):
    mine = await add_req(session, env.owner, booking=env.booking, key="HMS-5", status="В работе", status_category="indeterminate")
    failed = await add_req(session, env.owner, kind="return", key=None, error="Jira лежит")  # без ключа — url пустой
    await add_req(session, env.stranger, key="HMS-9")
    login(env.owner)
    r = await client.get(api("/requests/my"))
    assert r.status_code == 200
    by_id = {x["id"]: x for x in r.json()}
    assert set(by_id) == {mine.id, failed.id}  # заявка чужой команды не попала
    assert by_id[failed.id]["url"] is None and by_id[failed.id]["error"] == "Jira лежит"
    assert by_id[mine.id]["url"] == "https://jira.test/plugins/servlet/desk/portal/54/HMS-5"
    assert by_id[mine.id]["status"] == "В работе" and by_id[mine.id]["kind"] == "problem"
    assert by_id[mine.id]["customer_status"] == "В работе" and by_id[mine.id]["customer_note"] is None


async def test_my_requests_show_customer_status_and_frozen_note(client, login, api, session, env, sd):
    """Заказчику — слова из таблицы статусов, а не названия workflow Jira; «Заморожено» с комментарием исполнителя."""
    frozen = await add_req(session, env.owner, key="DR-1", status="Frozen", status_note="Ждём SSD")
    taken_back = await add_req(session, env.owner, key="DR-2", status="Backlog", was_taken=True)
    login(env.owner)
    by_id = {x["id"]: x for x in (await client.get(api("/requests/my"))).json()}
    assert (by_id[frozen.id]["customer_status"], by_id[frozen.id]["customer_note"]) == ("Заморожено", "Ждём SSD")
    assert by_id[taken_back.id]["customer_status"] == "Снято с исполнителя"


async def test_my_requests_empty(client, login, api, env, sd):
    login(env.stranger)
    assert (await client.get(api("/requests/my"))).json() == []


# ---------- POST /requests ----------

async def test_create_request_for_booking_201(client, login, api, env, sd):
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "Не включается"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "problem" and body["booking_id"] == env.booking.id and body["vm_id"] is None
    assert body["issue_key"] == "HMS-1" and body["status"] == "Ожидает поддержки" and body["status_category"] == "new"
    assert body["url"].endswith("/portal/54/HMS-1") and body["error"] is None
    assert [x.issue_key for x in await rows()] == ["HMS-1"]


async def test_create_request_trims_message(client, login, api, env, sd):
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "  Не включается  \n"})
    assert r.status_code == 201
    assert sd.created[0][2].startswith("Не включается\n\n---\n")


async def test_create_request_for_vm_201(client, login, api, env, sd):
    login(env.mate)  # коллега по команде
    r = await client.post(api("/requests"), json={"vm_id": env.vm.id, "message": "Нет сети"})
    assert r.status_code == 201 and r.json()["vm_id"] == env.vm.id


@pytest.mark.parametrize("body", [
    {"message": "Проблема"},  # ни booking_id, ни vm_id
    {"booking_id": 1, "vm_id": 1, "message": "Проблема"},  # оба
    {"booking_id": 1, "message": "1234"},  # короткое сообщение
    {"booking_id": 1, "message": ""},
    {"booking_id": 1},
    {"booking_id": 1, "message": "x" * 5001},
    {"booking_id": 0, "message": "Проблема"},  # 0 — «не указан»
    {"booking_id": 1, "message": "         "},  # одни пробелы не должны превращаться в пустую заявку в Jira
    {"booking_id": 1, "message": "  abc  "},  # после обрезки пробелов короче 5 символов
], ids=["no-target", "both", "short", "empty", "no-message", "too-long", "zero-id", "spaces", "short-after-trim"])
async def test_create_request_validation_422(client, login, api, env, sd, body):
    login(env.owner)
    assert (await client.post(api("/requests"), json=body)).status_code == 422
    assert sd.created == [] and await rows() == []


@pytest.mark.parametrize("body, code", [
    ({"booking_id": 999, "message": "Проблема"}, 404),
    ({"vm_id": 999, "message": "Проблема"}, 404),
])
async def test_create_request_unknown_target_404(client, login, api, env, sd, body, code):
    login(env.owner)
    assert (await client.post(api("/requests"), json=body)).status_code == code


async def test_create_request_foreign_is_403(client, login, api, env, sd):
    login(env.stranger)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "Проблема"})
    assert r.status_code == 403 and sd.created == []


async def test_create_request_not_configured_is_400(client, login, api, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_token", "")
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "Проблема"})
    assert r.status_code == 400 and "не подключены" in r.json()["detail"]


async def test_create_request_jira_error_is_400_and_not_saved(client, login, api, env, sd):
    sd.create_error = boom("Service Desk 500: boom")
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "Проблема"})
    assert r.status_code == 400 and "Не удалось создать заявку" in r.json()["detail"]
    assert await rows() == []


# ---------- GET /requests/{id} ----------

async def test_request_detail_with_comments_and_fresh_status(client, login, api, session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking, status="Старый", status_category="new")
    sd.status = real_sd.SdStatus("Решено", "done")
    sd.comments = [real_sd.SdComment("Админ", "Починили", "2026-01-01T10:00:00+0000", False),
                   real_sd.SdComment("Сервис", "[HMS Rent] Иван: спасибо", None, True)]
    login(env.mate)
    r = await client.get(api(f"/requests/{req.id}"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["request"]["status"] == "Решено" and body["request"]["status_category"] == "done"
    assert body["request"]["url"].endswith("/portal/54/HMS-100")
    assert body["comments"] == [
        {"author": "Админ", "body": "Починили", "created": "2026-01-01T10:00:00+0000", "from_portal": False},
        {"author": "Сервис", "body": "[HMS Rent] Иван: спасибо", "created": None, "from_portal": True},
    ]
    assert (await fresh(req.id)).status_category == "done"


async def test_request_detail_without_issue_key(client, login, api, session, env, sd):
    req = await add_req(session, env.owner, key=None, kind="return", error="Jira лежит")
    login(env.owner)
    body = (await client.get(api(f"/requests/{req.id}"))).json()
    assert body["comments"] == [] and body["request"]["url"] is None and body["request"]["error"] == "Jira лежит"


async def test_request_detail_foreign_is_403(client, login, api, session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking)
    login(env.stranger)
    assert (await client.get(api(f"/requests/{req.id}"))).status_code == 403


async def test_request_detail_admin_allowed(client, login, api, session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking)
    login(env.admin)
    assert (await client.get(api(f"/requests/{req.id}"))).status_code == 200


async def test_request_detail_unknown_is_404(client, login, api, env, sd):
    login(env.owner)
    assert (await client.get(api("/requests/999"))).status_code == 404


async def test_request_detail_jira_down_is_400(client, login, api, session, env, sd):
    req = await add_req(session, env.owner)
    sd.comments_error = boom()
    login(env.owner)
    r = await client.get(api(f"/requests/{req.id}"))
    assert r.status_code == 400 and r.json()["detail"] == "Service Desk отклонил запрос, попробуйте позже"


# ---------- POST /requests/{id}/comments ----------

async def test_add_comment_204(client, login, api, session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking)
    login(env.mate)
    r = await client.post(api(f"/requests/{req.id}/comments"), json={"message": "  Спасибо  "})
    assert r.status_code == 204 and r.content == b""
    assert sd.sent == [("HMS-100", "mate", "Спасибо")]


@pytest.mark.parametrize("body", [{"message": ""}, {}, {"message": "x" * 5001}, {"message": "   \n "}],
                         ids=["empty", "missing", "too-long", "spaces"])
async def test_add_comment_validation_422(client, login, api, session, env, sd, body):
    req = await add_req(session, env.owner)
    login(env.owner)
    assert (await client.post(api(f"/requests/{req.id}/comments"), json=body)).status_code == 422
    assert sd.sent == []


@pytest.mark.parametrize("who, code", [("stranger", 403)])
async def test_add_comment_foreign_is_403(client, login, api, session, env, sd, who, code):
    req = await add_req(session, env.owner, booking=env.booking)
    login(getattr(env, who))
    assert (await client.post(api(f"/requests/{req.id}/comments"), json={"message": "ok"})).status_code == code
    assert sd.sent == []


async def test_add_comment_unknown_is_404(client, login, api, env, sd):
    login(env.owner)
    assert (await client.post(api("/requests/999/comments"), json={"message": "ok"})).status_code == 404


async def test_add_comment_jira_error_is_400(client, login, api, session, env, sd):
    req = await add_req(session, env.owner)
    sd.send_error = boom()
    login(env.owner)
    r = await client.post(api(f"/requests/{req.id}/comments"), json={"message": "ok"})
    assert r.status_code == 400 and "Не удалось отправить сообщение" in r.json()["detail"]


# ---------- возврат ПК создаёт заявку «Возврат» ----------

async def test_return_creates_return_request_in_background(client, login, api, env, sd):
    login(env.owner)
    r = await client.post(api(f"/bookings/{env.booking.id}/return"), json={"comment": "Всё цело"})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    [req] = await rows()
    assert (req.kind, req.user_id, req.booking_id, req.issue_key, req.error) == ("return", env.owner.id, env.booking.id, "HMS-1", None)
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (1252, "owner") and "возврат ПК A001" in summary
    assert "Комментарий при возврате: Всё цело" in description and "Вернул: Иван Иванов" in description


async def test_return_by_admin_records_admin_as_actor(client, login, api, env, sd):
    login(env.admin)
    assert (await client.post(api(f"/bookings/{env.booking.id}/return"), json={})).status_code == 200
    [req] = await rows()
    assert req.user_id == env.admin.id and sd.created[0][3] == "admin"


async def test_return_survives_jira_error(client, login, api, env, sd):
    sd.create_error = boom("Service Desk 503: down")
    login(env.owner)
    r = await client.post(api(f"/bookings/{env.booking.id}/return"), json={})
    assert r.status_code == 200 and r.json()["status"] == "returned"
    [req] = await rows()
    assert req.issue_key is None and req.error == "Service Desk отклонил запрос, попробуйте позже" and "503" not in req.error


@pytest.mark.parametrize("field, value", [("sd_token", ""), ("sd_return_on_return", False)])
async def test_return_without_request_when_disabled(client, login, api, env, sd, monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    login(env.owner)
    assert (await client.post(api(f"/bookings/{env.booking.id}/return"), json={})).status_code == 200
    assert sd.created == [] and await rows() == []


async def test_failed_return_creates_no_request(client, login, api, env, sd):
    """Чужой пользователь (403) и повторный возврат (409) заявок не плодят."""
    login(env.stranger)
    assert (await client.post(api(f"/bookings/{env.booking.id}/return"), json={})).status_code == 403
    login(env.owner)
    await client.post(api(f"/bookings/{env.booking.id}/return"), json={})
    assert (await client.post(api(f"/bookings/{env.booking.id}/return"), json={})).status_code == 409
    assert len(sd.created) == 1


# ---------- заказ физического ПК: ОС и сборка по запросу ----------

async def test_order_options_give_os_and_builds(client, login, api, env):
    login(env.owner)
    body = (await client.get(api("/catalog/order-options"))).json()
    assert body == {"os": default_pc_os(), "builds": default_pc_builds(),
                    "build_wanted_min": earliest_wanted_by().isoformat()}  # норматив сборки — 3 рабочих дня


async def test_order_options_follow_settings(client, login, api, env, session):
    await runtime.update(session, {"pc_os_list": ["  Astra Linux  "], "pc_builds": []})
    login(env.owner)
    assert (await client.get(api("/catalog/order-options"))).json() == {
        "os": ["Astra Linux"], "builds": [], "build_wanted_min": earliest_wanted_by().isoformat()}


def _build_body(env, **kw) -> dict:
    return {"build": default_pc_builds()[1], "os_label": "Ubuntu 24.04", "department_id": env.qa.id,
            "requester_nick": "ivan",
            "expected_return_at": (clock.today() + timedelta(days=20)).isoformat()} | kw


async def test_create_build_201_and_team_sees_it(client, login, api, env, sd):
    login(env.owner)
    r = await client.post(api("/requests/build"), json=_build_body(env))
    assert r.status_code == 201, r.text
    assert (r.json()["kind"], r.json()["department_id"], r.json()["issue_key"]) == ("build", env.qa.id, "HMS-1")
    assert "сборка ПК — тип B" in r.json()["summary"]
    login(env.mate)
    assert [x["id"] for x in (await client.get(api("/requests/my"))).json()] == [r.json()["id"]]
    login(env.stranger)
    assert (await client.get(api("/requests/my"))).json() == []


@pytest.mark.parametrize("kw", [{"build": None}, {"os_label": ""}, {"expected_return_at": "2020-01-01"},
                                {"wanted_by": "не дата"}], ids=["no-variant", "no-os", "past", "garbage"])
async def test_create_build_validation_422(client, login, api, env, sd, kw):
    login(env.owner)
    assert (await client.post(api("/requests/build"), json=_build_body(env, **kw))).status_code == 422
    assert await rows() == []


async def test_create_build_unknown_os_400_and_foreign_department_403(client, login, api, env, sd, session):
    login(env.owner)
    assert (await client.post(api("/requests/build"), json=_build_body(env, os_label="MS-DOS"))).status_code == 400
    assert (await client.post(api("/requests/build"), json=_build_body(env, department_id=999))).status_code == 403
    assert await rows() == []


async def test_booking_with_os_creates_prepare_request(client, login, api, env, sd, make_pool, make_computer):
    comp = await make_computer("A002", await make_pool("Second"), insight_status="Свободен")
    login(env.owner)
    r = await client.post(api("/bookings"), json={
        "computer_id": comp.id, "department_id": env.qa.id, "requester_nick": "ivan",
        "expected_return_at": (clock.today() + timedelta(days=10)).isoformat(), "os_label": "Windows Server 2025"})
    assert r.status_code == 201, r.text
    assert r.json()["os_label"] == "Windows Server 2025"
    [req] = await rows()
    assert (req.kind, req.booking_id, req.user_id) == ("prepare", r.json()["id"], env.owner.id)
    _, summary, description, _ = sd.created[0]
    assert summary == f"HMS Rent: подготовить ПК A002 (заказ №{r.json()['order_number']})"
    assert "ОС: Windows Server 2025" in description


async def test_booking_with_unknown_os_400(client, login, api, env, sd, make_pool, make_computer):
    comp = await make_computer("A002", await make_pool("Second"), insight_status="Свободен")
    login(env.owner)
    r = await client.post(api("/bookings"), json={
        "computer_id": comp.id, "department_id": env.qa.id, "requester_nick": "ivan",
        "expected_return_at": (clock.today() + timedelta(days=10)).isoformat(), "os_label": "MS-DOS"})
    assert r.status_code == 400
    assert await rows() == [] and sd.created == []
