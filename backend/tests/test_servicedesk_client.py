"""Клиент Jira Service Desk (app/integrations/servicedesk.py): заявки, статусы, комментарии, авторизация, ошибки.

Сеть не используется: httpx мокается через respx, настройки меняются monkeypatch'ем.
"""
import base64
import json
import logging

import httpx
import pytest
import respx

from app.core.config import settings
from app.integrations import servicedesk as sd

BASE = "https://jira.test"
API = BASE + "/rest/servicedeskapi"
TOKEN = "SECRET-TOKEN-123"
PASSWORD = "p@ss-w0rd-XYZ"


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    """Service Desk настроен по токену; «на чьё имя» включено."""
    for k, v in dict(sd_jira_url=BASE, sd_token=TOKEN, sd_username="", sd_password="", sd_service_desk_id=54,
                     sd_raise_on_behalf=True, sd_verify_ssl=True).items():
        monkeypatch.setattr(settings, k, v)


@pytest.fixture
def jira():
    with respx.mock(assert_all_called=False) as router:
        yield router


def created(key="HMS-1", status="Ожидает поддержки", category="NEW") -> dict:
    return {"issueKey": key, "currentStatus": {"status": status, "statusCategory": category}}


def sent(route, n=-1) -> dict:
    return json.loads(route.calls[n].request.content)


# ---------- create_request ----------

async def test_create_request_success(jira):
    route = jira.post(f"{API}/request").respond(201, json=created("HMS-7", "В работе", "INDETERMINATE"))
    key, status = await sd.create_request(1248, "Описание", "ivanov")
    assert key == "HMS-7" and status == sd.SdStatus("В работе", "indeterminate")
    assert route.call_count == 1
    assert sent(route) == {"serviceDeskId": "54", "requestTypeId": "1248", "raiseOnBehalfOf": "ivanov",
                           "requestFieldValues": {"description": "Описание"}}  # темы в форме «Прочее» нет: ей Jira ставит название типа


@pytest.mark.parametrize("behalf, switch", [(None, True), ("", True), ("ivanov", False)], ids=["no-login", "empty-login", "switch-off"])
async def test_create_request_without_raise_on_behalf(jira, monkeypatch, behalf, switch):
    monkeypatch.setattr(settings, "sd_raise_on_behalf", switch)
    route = jira.post(f"{API}/request").respond(201, json=created())
    await sd.create_request(1248, "D", behalf)
    assert route.call_count == 1 and "raiseOnBehalfOf" not in sent(route)


@pytest.mark.parametrize("code", [400, 403, 404])
async def test_create_request_unknown_jira_user_falls_back_to_service_account(jira, code):
    """Jira не знает сотрудника: повтор без raiseOnBehalfOf (автор — в описании, его кладёт сервис)."""
    route = jira.post(f"{API}/request").mock(side_effect=[
        httpx.Response(code, json={"errorMessage": "user not found"}),
        httpx.Response(201, json=created("HMS-9")),
    ])
    key, status = await sd.create_request(1248, "Описание с автором", "ghost")
    assert key == "HMS-9" and status.category == "new"
    assert route.call_count == 2
    assert sent(route, 0)["raiseOnBehalfOf"] == "ghost"
    assert "raiseOnBehalfOf" not in sent(route, 1)
    assert sent(route, 1)["requestFieldValues"]["description"] == "Описание с автором"


async def test_create_request_both_attempts_fail(jira):
    route = jira.post(f"{API}/request").mock(side_effect=[
        httpx.Response(400, json={"errorMessage": "user not found"}),
        httpx.Response(400, json={"errors": {"customfield_1": "обязательное поле"}}),
    ])
    with pytest.raises(sd.ServiceDeskError, match="400.*customfield_1: обязательное поле"):
        await sd.create_request(1248, "D", "ghost")
    assert route.call_count == 2


@pytest.mark.parametrize("resp, text", [
    (httpx.Response(400, json={"errorMessage": "Плохой тип"}), "Service Desk 400: Плохой тип"),
    (httpx.Response(403, json={"errorMessages": ["a", "b"]}), "Service Desk 403: a; b"),
    (httpx.Response(400, json={"errors": {"summary": "пусто", "x": "y"}}), "Service Desk 400: summary: пусто; x: y"),
    (httpx.Response(500, text="Internal boom"), "Service Desk 500: Internal boom"),
    (httpx.Response(502, text="x" * 500), "Service Desk 502: " + "x" * 200),  # длинный текст обрезается
    (httpx.Response(401, json={}), "Service Desk 401: {}"),
], ids=["errorMessage", "errorMessages", "errors", "plain-text", "truncated", "empty-json"])
async def test_create_request_http_errors(jira, resp, text):
    jira.post(f"{API}/request").mock(return_value=resp)
    with pytest.raises(sd.ServiceDeskError) as e:
        await sd.create_request(1248, "D", None)
    assert str(e.value) == text


# ---------- get_status / get_comments / add_comment / request_type_fields ----------

async def test_get_status(jira):
    jira.get(f"{API}/request/HMS-5").respond(200, json=created("HMS-5", "Решено", "DONE"))
    assert await sd.get_status("HMS-5") == sd.SdStatus("Решено", "done")


@pytest.mark.parametrize("data, expected", [
    ({"currentStatus": {"status": "Открыта"}}, sd.SdStatus("Открыта", None)),  # без категории
    ({}, sd.SdStatus(None, None)),  # без статуса вообще
    ({"currentStatus": {"status": "X", "statusCategory": None}}, sd.SdStatus("X", None)),
], ids=["no-category", "empty", "null-category"])
async def test_get_status_partial(jira, data, expected):
    jira.get(f"{API}/request/HMS-5").respond(200, json=data)
    assert await sd.get_status("HMS-5") == expected


async def test_get_comments_public_only_and_flags(jira):
    route = jira.get(f"{API}/request/HMS-5/comment").respond(200, json={"values": [
        {"author": {"displayName": "Админ"}, "body": "Починили", "created": {"iso8601": "2026-01-02T10:00:00+0000"}},
        {"author": {"displayName": "Сервис"}, "body": "[HMS Rent] Иван: спасибо", "created": {"iso8601": "2026-01-02T11:00:00+0000"}},
        {"body": None, "created": None},  # без автора, текста и даты
        {"author": {"displayName": "Админ"}, "body": "про [HMS Rent] внутри"},  # префикс только в начале
    ]})
    comments = await sd.get_comments("HMS-5")
    # Внутренние заметки отсекает сама Jira по параметрам запроса: проверяем, что мы их запросили именно так
    assert dict(route.calls.last.request.url.params) == {"public": "true", "internal": "false", "start": "0", "limit": "100"}
    assert comments == [
        sd.SdComment("Админ", "Починили", "2026-01-02T10:00:00+0000", False),
        sd.SdComment("Сервис", "[HMS Rent] Иван: спасибо", "2026-01-02T11:00:00+0000", True),
        sd.SdComment("Поддержка", "", None, False),
        sd.SdComment("Админ", "про [HMS Rent] внутри", None, False),
    ]


async def test_get_comments_reads_all_pages(jira):
    def page(n, last):
        return {"isLastPage": last, "values": [{"author": {"displayName": "А"}, "body": f"№{n}-{i}"} for i in range(2)]}

    route = jira.get(f"{API}/request/HMS-5/comment").mock(side_effect=[
        httpx.Response(200, json=page(1, False)), httpx.Response(200, json=page(2, False)),
        httpx.Response(200, json=page(3, True)),
    ])
    comments = await sd.get_comments("HMS-5")
    assert [c.body for c in comments] == ["№1-0", "№1-1", "№2-0", "№2-1", "№3-0", "№3-1"]
    assert [call.request.url.params["start"] for call in route.calls] == ["0", "2", "4"]  # старт сдвигается на прочитанное


async def test_get_comments_stops_at_page_limit(jira):
    route = jira.get(f"{API}/request/HMS-5/comment").respond(
        200, json={"isLastPage": False, "values": [{"body": "x"}]})  # сервер «никогда не заканчивает»
    comments = await sd.get_comments("HMS-5")
    assert len(comments) == len(route.calls) == sd.COMMENT_PAGES


async def test_get_comments_stops_on_empty_page_even_without_last_flag(jira):
    route = jira.get(f"{API}/request/HMS-5/comment").respond(200, json={"isLastPage": False, "values": []})
    assert await sd.get_comments("HMS-5") == [] and len(route.calls) == 1


async def test_get_comments_empty(jira):
    jira.get(f"{API}/request/HMS-5/comment").respond(200, json={})
    assert await sd.get_comments("HMS-5") == []


async def test_add_comment_format_and_public(jira):
    route = jira.post(f"{API}/request/HMS-5/comment").respond(201, json={})
    await sd.add_comment("HMS-5", "Иван Иванов", "Не помогло")
    assert sent(route) == {"body": "[HMS Rent] Иван Иванов: Не помогло", "public": True}
    assert sent(route)["body"].startswith(sd.PORTAL_PREFIX)


async def test_request_type_fields(jira):
    fields = [{"fieldId": "summary", "required": True}, {"fieldId": "description", "required": False}]
    route = jira.get(f"{API}/servicedesk/54/requesttype/1248/field").respond(200, json={"requestTypeFields": fields})
    assert await sd.request_type_fields(1248) == fields
    assert route.call_count == 1


async def test_request_type_fields_uses_configured_desk_and_empty(jira, monkeypatch):
    monkeypatch.setattr(settings, "sd_service_desk_id", 7)
    jira.get(f"{API}/servicedesk/7/requesttype/1252/field").respond(200, json={})
    assert await sd.request_type_fields(1252) == []


CALLS = {
    "create": (lambda: sd.create_request(1248, "D", None), "post", "/request"),
    "status": (lambda: sd.get_status("HMS-5"), "get", "/request/HMS-5"),
    "comments": (lambda: sd.get_comments("HMS-5"), "get", "/request/HMS-5/comment"),
    "add_comment": (lambda: sd.add_comment("HMS-5", "И", "т"), "post", "/request/HMS-5/comment"),
    "fields": (lambda: sd.request_type_fields(1248), "get", "/servicedesk/54/requesttype/1248/field"),
}


@pytest.mark.parametrize("code", [400, 401, 403, 404, 500, 503])
@pytest.mark.parametrize("name", CALLS)
async def test_every_call_maps_http_errors_to_servicedesk_error(jira, name, code):
    call, method, path = CALLS[name]
    getattr(jira, method)(f"{API}{path}").respond(code, json={"errorMessage": "нет доступа"})
    with pytest.raises(sd.ServiceDeskError, match=f"Service Desk {code}: нет доступа"):
        await call()


# ---------- настройки и авторизация ----------

@pytest.mark.parametrize("url, expected", [
    (BASE, f"{BASE}/plugins/servlet/desk/portal/54/HMS-3"),
    (BASE + "/", f"{BASE}/plugins/servlet/desk/portal/54/HMS-3"),  # слэш в конце не дублируется
], ids=["plain", "trailing-slash"])
def test_portal_url(monkeypatch, url, expected):
    monkeypatch.setattr(settings, "sd_jira_url", url)
    assert sd.portal_url("HMS-3") == expected


def test_portal_url_uses_service_desk_id(monkeypatch):
    monkeypatch.setattr(settings, "sd_service_desk_id", 99)
    assert sd.portal_url("HMS-3") == f"{BASE}/plugins/servlet/desk/portal/99/HMS-3"


async def test_bearer_token_auth_and_headers(jira):
    route = jira.get(f"{API}/request/HMS-5").respond(200, json=created())
    await sd.get_status("HMS-5")
    h = route.calls.last.request.headers
    assert h["Authorization"] == f"Bearer {TOKEN}"
    assert h["Accept"] == "application/json" and h["X-ExperimentalApi"] == "opt-in"


async def test_basic_auth_without_token(jira, monkeypatch):
    monkeypatch.setattr(settings, "sd_token", "")
    monkeypatch.setattr(settings, "sd_username", "svc")
    monkeypatch.setattr(settings, "sd_password", PASSWORD)
    route = jira.get(f"{API}/request/HMS-5").respond(200, json=created())
    await sd.get_status("HMS-5")
    expected = "Basic " + base64.b64encode(f"svc:{PASSWORD}".encode()).decode()
    assert route.calls.last.request.headers["Authorization"] == expected


async def test_token_wins_over_password(jira, monkeypatch):
    monkeypatch.setattr(settings, "sd_username", "svc")
    monkeypatch.setattr(settings, "sd_password", PASSWORD)
    route = jira.get(f"{API}/request/HMS-5").respond(200, json=created())
    await sd.get_status("HMS-5")
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize("name", CALLS)
@pytest.mark.parametrize("token, url", [("", BASE), (TOKEN, "")], ids=["no-credentials", "no-url"])
async def test_not_configured_raises_without_request(jira, monkeypatch, name, token, url):
    monkeypatch.setattr(settings, "sd_token", token)
    monkeypatch.setattr(settings, "sd_jira_url", url)
    with pytest.raises(sd.ServiceDeskError, match="Service Desk не настроен"):
        await CALLS[name][0]()
    assert not jira.calls


async def test_not_configured_message_has_no_secrets(monkeypatch):
    monkeypatch.setattr(settings, "sd_token", "")
    monkeypatch.setattr(settings, "sd_password", PASSWORD)  # пароль без логина — всё ещё «не настроен»
    with pytest.raises(sd.ServiceDeskError) as e:
        await sd.get_status("HMS-5")
    assert PASSWORD not in str(e.value)


async def test_secrets_not_in_errors_and_logs(jira, monkeypatch, caplog):
    """Токен и пароль не попадают ни в текст ошибки, ни в логи (в т.ч. при откате с raiseOnBehalfOf)."""
    caplog.set_level(logging.DEBUG)
    for token, user, pwd in [(TOKEN, "", ""), ("", "svc", PASSWORD)]:
        monkeypatch.setattr(settings, "sd_token", token)
        monkeypatch.setattr(settings, "sd_username", user)
        monkeypatch.setattr(settings, "sd_password", pwd)
        jira.post(f"{API}/request").respond(400, json={"errorMessage": "плохо"})
        with pytest.raises(sd.ServiceDeskError) as e:
            await sd.create_request(1248, "D", "ghost")
        blob = str(e.value) + caplog.text
        assert TOKEN not in blob and PASSWORD not in blob
        assert base64.b64encode(f"svc:{PASSWORD}".encode()).decode() not in blob


async def test_client_has_timeout_and_base_url():
    async with sd._client() as http:
        assert http.timeout == httpx.Timeout(20)  # внешний вызов всегда с таймаутом
        assert http.base_url == httpx.URL(API + "/")


# ---------- сетевые сбои ----------

@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")], ids=["connect", "timeout"])
@pytest.mark.parametrize("name", CALLS)
async def test_network_errors_become_servicedesk_error(jira, name, exc):
    call, method, path = CALLS[name]
    getattr(jira, method)(f"{API}{path}").mock(side_effect=exc)
    with pytest.raises(sd.ServiceDeskError):
        await call()


@pytest.mark.parametrize("name", ["create", "status", "comments", "fields"])
async def test_non_json_success_becomes_servicedesk_error(jira, name):
    call, method, path = CALLS[name]
    getattr(jira, method)(f"{API}{path}").respond(200, text="<html>login page</html>")
    with pytest.raises(sd.ServiceDeskError):
        await call()


async def test_create_without_issue_key_becomes_servicedesk_error(jira):
    jira.post(f"{API}/request").respond(201, json={"id": "1"})
    with pytest.raises(sd.ServiceDeskError):
        await sd.create_request(1248, "D", None)


async def test_error_body_json_array(jira):
    jira.get(f"{API}/request/HMS-5").respond(500, json=["boom"])
    with pytest.raises(sd.ServiceDeskError):
        await sd.get_status("HMS-5")


# ---------- Jira REST: история, переходы, закрытие ----------

REST = BASE + "/rest/api/2"


def history(*statuses: str) -> dict:
    return {"histories": [{"items": [{"field": "status", "toString": st}]} for st in statuses]}


async def test_get_details_reads_history_and_resolution(jira):
    route = jira.get(f"{REST}/issue/DR-1").respond(200, json={
        "fields": {"resolution": {"name": "Rejected"}},
        "changelog": {"histories": [{"items": [{"field": "assignee", "toString": "In Progress"}]},
                                    *history("In Progress", "Backlog")["histories"]]},
    })
    assert await sd.get_details("DR-1") == sd.SdDetails(taken=True, resolution="Rejected")
    assert dict(route.calls[0].request.url.params) == {"fields": "resolution", "expand": "changelog"}


async def test_get_details_never_taken_and_open(jira):
    jira.get(f"{REST}/issue/DR-1").respond(200, json={"fields": {"resolution": None}, "changelog": history("To Do")})
    assert await sd.get_details("DR-1") == sd.SdDetails(taken=False, resolution=None)


async def test_get_details_error_is_service_desk_error(jira):
    jira.get(f"{REST}/issue/DR-1").respond(403, json={"errorMessages": ["нет доступа"]})
    with pytest.raises(sd.ServiceDeskError, match="403: нет доступа"):
        await sd.get_details("DR-1")


async def test_transitions_lists_available(jira):
    jira.get(f"{REST}/issue/DR-1/transitions").respond(200, json={"transitions": [
        {"id": "151", "name": "Done", "to": {"name": "Done"}}]})
    assert (await sd.transitions("DR-1"))[0]["id"] == "151"


def open_issue(jira, status="Backlog", category="new"):
    jira.get(f"{REST}/issue/DR-1", params={"fields": "status"}).respond(
        200, json={"fields": {"status": {"name": status, "statusCategory": {"key": category}}}})


@pytest.mark.parametrize("resolution", [sd.RESOLUTION_DONE, sd.RESOLUTION_REJECTED])
async def test_close_issue_moves_to_done_with_resolution(jira, resolution):
    open_issue(jira)
    jira.get(f"{REST}/issue/DR-1/transitions").respond(200, json={"transitions": [
        {"id": "141", "name": "Backlog", "to": {"name": "Backlog"}}, {"id": "151", "name": "Done", "to": {"name": "Done"}}]})
    post = jira.post(f"{REST}/issue/DR-1/transitions").respond(204)
    assert await sd.close_issue("DR-1", resolution) is True
    assert sent(post) == {"transition": {"id": "151"}, "fields": {"resolution": {"name": resolution}}}


REAL_TRANSITIONS = [  # как отвечает Jira проекта DR: названия целевых статусов переведены
    {"id": "141", "name": "Backlog", "to": {"name": "Backlog", "statusCategory": {"key": "new"}}},
    {"id": "151", "name": "Done", "to": {"name": "Готово", "statusCategory": {"key": "done"}}},
    {"id": "161", "name": "In Progress", "to": {"name": "В работе", "statusCategory": {"key": "indeterminate"}}},
]


async def test_close_issue_finds_done_by_status_category_when_names_are_translated(jira):
    open_issue(jira)
    jira.get(f"{REST}/issue/DR-1/transitions").respond(200, json={"transitions": REAL_TRANSITIONS})
    post = jira.post(f"{REST}/issue/DR-1/transitions").respond(204)
    assert await sd.close_issue("DR-1", sd.RESOLUTION_DONE) is True
    assert sent(post)["transition"] == {"id": "151"}


@pytest.mark.parametrize("target, expected", [
    ({"name": "Готово", "statusCategory": {"key": "done"}}, True),
    ({"name": "Готово"}, True),  # категории в ответе нет — по переведённому названию
    ({"name": "Done"}, True),
    ({"name": "Закрыто", "statusCategory": {"key": "done"}}, True),  # любое название, главное — категория
    ({"name": "В работе", "statusCategory": {"key": "indeterminate"}}, False),
    ({}, False),
])
def test_is_done_transition(target, expected):
    assert sd.is_done_transition({"id": "1", "to": target}) is expected


async def test_get_details_sees_translated_in_progress(jira):
    jira.get(f"{REST}/issue/DR-1").respond(200, json={"fields": {"resolution": None}, "changelog": history("В работе")})
    assert (await sd.get_details("DR-1")).taken is True


async def test_close_issue_already_done_is_noop(jira):
    open_issue(jira, "Done", "done")
    post = jira.post(f"{REST}/issue/DR-1/transitions").respond(204)
    assert await sd.close_issue("DR-1", sd.RESOLUTION_DONE) is False
    assert post.call_count == 0


async def test_close_issue_without_done_transition(jira):
    open_issue(jira, "Frozen", "indeterminate")
    jira.get(f"{REST}/issue/DR-1/transitions").respond(200, json={"transitions": []})
    with pytest.raises(sd.ServiceDeskError, match="Из статуса «Frozen» нет перехода в Done"):
        await sd.close_issue("DR-1", sd.RESOLUTION_DONE)


async def test_close_issue_transition_rejected_by_jira(jira):
    open_issue(jira)
    jira.get(f"{REST}/issue/DR-1/transitions").respond(200, json={"transitions": [
        {"id": "151", "name": "Done", "to": {"name": "Done"}}]})
    jira.post(f"{REST}/issue/DR-1/transitions").respond(400, json={"errors": {"resolution": "не задана"}})
    with pytest.raises(sd.ServiceDeskError, match="resolution: не задана"):
        await sd.close_issue("DR-1", sd.RESOLUTION_REJECTED)


async def test_close_issue_status_read_error(jira):
    jira.get(f"{REST}/issue/DR-1").respond(404, json={"errorMessages": ["нет задачи"]})
    with pytest.raises(sd.ServiceDeskError, match="404"):
        await sd.close_issue("DR-1", sd.RESOLUTION_DONE)


def test_issue_fields_default_and_env_override(monkeypatch):
    from app.core.config import Settings
    assert Settings(_env_file=None).sd_issue_fields == {"components": [{"name": "HMS"}], "customfield_10002": "DR-69"}
    monkeypatch.setenv("SD_ISSUE_FIELDS", '{"components": [{"name": "OPS"}]}')
    assert Settings(_env_file=None).sd_issue_fields == {"components": [{"name": "OPS"}]}
    monkeypatch.setenv("SD_ISSUE_FIELDS", "{}")
    assert Settings(_env_file=None).sd_issue_fields == {}


async def test_update_issue_puts_fields(jira):
    route = jira.put(f"{REST}/issue/DR-1").respond(204)
    await sd.update_issue("DR-1", {"components": [{"name": "HMS"}]})
    assert sent(route) == {"fields": {"components": [{"name": "HMS"}]}}


async def test_update_issue_error_is_service_desk_error(jira):
    jira.put(f"{REST}/issue/DR-1").respond(400, json={"errors": {"components": "не найден"}})
    with pytest.raises(sd.ServiceDeskError, match="components: не найден"):
        await sd.update_issue("DR-1", {"components": [{"name": "X"}]})
