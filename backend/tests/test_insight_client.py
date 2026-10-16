"""HTTP-клиент Insight (live): чтение IQL/AQL, пагинация, разбор атрибутов, запись, авторизация, ошибки.

Сеть не используется: httpx мокается через respx. Образцы ответов — в insight_samples.py.
"""
import base64
import json
import logging

import httpx
import pytest
import respx

from app.core.config import Settings
from app.integrations.insight import client as client_module
from app.integrations.insight.base import InsightError, InsightObject
from app.integrations.insight.client import InsightClient
from app.integrations.insight.mapping import InsightMapping

from .insight_samples import REF_TYPE_ID, TYPE_ATTRS, TYPE_ID, attr, entry, page, val

BASE = "https://jira.test"
API = BASE + "/rest/insight/1.0"
TOKEN = "SECRET-TOKEN-123"
PASSWORD = "p@ss-w0rd-XYZ"


def make_settings(**kw) -> Settings:
    kw.setdefault("jira_url", BASE)
    return Settings(_env_file=None, **kw)


@pytest.fixture
def api():
    """Перехват всех запросов к jira.test; атрибуты типа 21 отдаются всегда."""
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{API}/objecttype/{TYPE_ID}/attributes").respond(200, json=TYPE_ATTRS)
        yield router


@pytest.fixture
async def make_client():
    created: list[InsightClient] = []

    def _make(mapping: InsightMapping | None = None, **kw) -> InsightClient:
        c = InsightClient(make_settings(**kw), mapping or InsightMapping(query='objectType = "Automat"', schema_id=1))
        created.append(c)
        return c

    yield _make
    for c in created:
        await c.close()


@pytest.fixture
async def cl(make_client):
    return make_client(insight_token=TOKEN)


def params(route) -> httpx.QueryParams:
    return route.calls.last.request.url.params


# ---------- конструктор / авторизация ----------

async def test_no_jira_url_raises():
    with pytest.raises(InsightError, match="JIRA_URL"):
        InsightClient(make_settings(jira_url=""), InsightMapping(query="q"))


async def test_trailing_slash_in_jira_url_is_stripped(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(jira_url=BASE + "///").fetch_objects()
    assert route.called


async def test_bearer_header(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(insight_token=TOKEN).fetch_objects()
    req = route.calls.last.request
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["Accept"] == "application/json"


async def test_basic_auth_header(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(insight_username="svc", insight_password=PASSWORD).fetch_objects()
    expected = "Basic " + base64.b64encode(f"svc:{PASSWORD}".encode()).decode()
    assert route.calls.last.request.headers["Authorization"] == expected


async def test_token_wins_over_basic(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(insight_token=TOKEN, insight_username="svc", insight_password=PASSWORD).fetch_objects()
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_no_credentials_no_authorization_header(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client().fetch_objects()
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize("verify", [True, False])
async def test_verify_ssl_and_timeout_passed_to_httpx(monkeypatch, make_client, verify):
    captured = {}
    real = httpx.AsyncClient

    def spy(**kw):
        captured.update(kw)
        return real(**kw)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", spy)
    make_client(insight_verify_ssl=verify)
    assert captured["verify"] is verify
    assert captured["timeout"] == 30
    assert captured["base_url"] == API


async def test_close_closes_http_client(make_client):
    c = make_client()
    assert not c._http.is_closed
    await c.close()
    assert c._http.is_closed
    await c.close()  # повторный вызов безопасен


# ---------- чтение: IQL / AQL ----------

async def test_iql_request_shape(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(insight_api="iql", insight_page_size=50).fetch_objects()
    p = params(route)
    assert p["iql"] == 'objectType = "Automat"'
    assert "qlQuery" not in p
    assert (p["page"], p["resultPerPage"], p["objectSchemaId"]) == ("1", "50", "1")
    assert p["includeAttributes"] == "true"
    assert p["includeTypeAttributes"] == "true"


async def test_aql_request_shape(api, make_client):
    iql = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    aql = api.get(f"{API}/aql/objects").respond(200, json=page([]))
    await make_client(insight_api="aql").fetch_objects()
    assert aql.called and not iql.called
    assert params(aql)["qlQuery"] == 'objectType = "Automat"'
    assert "iql" not in params(aql)


async def test_schema_id_omitted_when_not_set(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(InsightMapping(query="q", schema_id=None)).fetch_objects()
    assert "objectSchemaId" not in params(route)


async def test_custom_query_overrides_mapping(api, cl):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await cl.fetch_objects(query='Name = "A1"')
    assert params(route)["iql"] == 'Name = "A1"'


async def test_fetch_single_page(api, cl):
    api.get(f"{API}/iql/objects").respond(200, json=page([entry(1, "A001"), entry(2, "A002")], total=2))
    objs = await cl.fetch_objects()
    assert [(o.id, o.key, o.label, o.object_type, o.object_type_id) for o in objs] == [
        (1, "ITAM-1", "A001", "Компьютер", TYPE_ID), (2, "ITAM-2", "A002", "Компьютер", TYPE_ID)]
    assert all(isinstance(o, InsightObject) for o in objs)
    assert objs[0].attributes == {"Name": "A001"}


@pytest.mark.parametrize("body", [
    page([]), page([], total=0), {}, {"objectEntries": None}, {"objectEntries": [], "totalFilterCount": None},
])
async def test_fetch_empty_response(api, cl, body):
    route = api.get(f"{API}/iql/objects").respond(200, json=body)
    assert await cl.fetch_objects() == []
    assert route.call_count == 1


async def test_fetch_multiple_pages_stops_on_short_page(api, make_client):
    route = api.get(f"{API}/iql/objects")
    route.side_effect = [
        httpx.Response(200, json=page([entry(1), entry(2)])),
        httpx.Response(200, json=page([entry(3), entry(4)])),
        httpx.Response(200, json=page([entry(5)])),
    ]
    objs = await make_client(insight_page_size=2).fetch_objects()
    assert [o.id for o in objs] == [1, 2, 3, 4, 5]
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2", "3"]


async def test_fetch_stops_when_total_reached_without_extra_request(api, make_client):
    """Последняя страница ровно полная, но total известен: лишний пустой запрос не нужен."""
    route = api.get(f"{API}/iql/objects")
    route.side_effect = [
        httpx.Response(200, json=page([entry(1), entry(2)], total=4)),
        httpx.Response(200, json=page([entry(3), entry(4)], total=4)),
    ]
    objs = await make_client(insight_page_size=2).fetch_objects()
    assert [o.id for o in objs] == [1, 2, 3, 4]
    assert route.call_count == 2


async def test_fetch_full_last_page_without_total_ends_on_empty_page(api, make_client):
    route = api.get(f"{API}/iql/objects")
    route.side_effect = [
        httpx.Response(200, json=page([entry(1), entry(2)])),
        httpx.Response(200, json=page([])),
    ]
    objs = await make_client(insight_page_size=2).fetch_objects()
    assert [o.id for o in objs] == [1, 2]
    assert route.call_count == 2


async def test_fetch_limit_stops_early_and_shrinks_page(api, make_client):
    """limit (insight_max_objects из синхронизации) режет и размер страницы, и результат."""
    route = api.get(f"{API}/iql/objects").respond(200, json=page([entry(i) for i in range(1, 4)], total=100))
    objs = await make_client(insight_page_size=200).fetch_objects(limit=3)
    assert [o.id for o in objs] == [1, 2, 3]
    assert route.call_count == 1
    assert params(route)["resultPerPage"] == "3"


async def test_fetch_limit_across_pages_truncates_overshoot(api, make_client):
    """Сервер вернул больше, чем просили: результат всё равно обрезается до limit."""
    route = api.get(f"{API}/iql/objects")
    route.side_effect = [
        httpx.Response(200, json=page([entry(1), entry(2)], total=50)),
        httpx.Response(200, json=page([entry(3), entry(4)], total=50)),
    ]
    objs = await make_client(insight_page_size=2).fetch_objects(limit=3)
    assert [o.id for o in objs] == [1, 2, 3]
    assert route.call_count == 2


async def test_fetch_page_size_capped_by_limit_but_not_above_page_size(api, make_client):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([]))
    await make_client(insight_page_size=10).fetch_objects(limit=500)
    assert params(route)["resultPerPage"] == "10"


async def test_fetch_stops_at_1000_pages_when_server_never_ends(api, make_client):
    """Защита от бесконечного цикла: сервер без totalFilterCount всегда отдаёт полную страницу."""
    route = api.get(f"{API}/iql/objects").respond(200, json=page([entry(1)]))
    objs = await make_client(insight_page_size=1).fetch_objects()
    assert route.call_count == 1000
    assert len(objs) == 1000


async def test_count_uses_total_filter_count(api, cl):
    route = api.get(f"{API}/iql/objects").respond(200, json=page([entry(1)], total=1234))
    assert await cl.count("q") == 1234
    assert (params(route)["page"], params(route)["resultPerPage"]) == ("1", "1")


@pytest.mark.parametrize("body", [{}, {"totalFilterCount": None}, {"totalFilterCount": 0}])
async def test_count_missing_total_is_zero(api, cl, body):
    api.get(f"{API}/iql/objects").respond(200, json=body)
    assert await cl.count("q") == 0


# ---------- разбор атрибутов ----------

async def test_to_object_attribute_types(api, cl):
    e = entry(7, "A007", [
        attr(100, val("A007", "A007")),
        attr(101, val(None, None, status={"id": 3, "name": "Ожидает"})),               # статус
        attr(102, val("9", "X", referencedObject={"id": 9, "label": "Команда QA"})),    # ссылка на объект
        attr(105, val("jdoe", None, user={"name": "jdoe", "displayName": "John Doe"})),  # пользователь
        attr(103, val("2026-10-20T00:00:00.000Z", "20/Oct/26 12:00 AM")),               # дата: displayValue приоритетнее
        attr(104, val(5)),                                                              # число без displayValue
    ])
    api.get(f"{API}/object/7").respond(200, json=e)
    obj = await cl.get_object(7)
    assert obj.attributes == {
        "Name": "A007", "Статус": "Ожидает", "Команда-получатель": "Команда QA", "Владелец": "John Doe",
        "Срок использования": "20/Oct/26 12:00 AM", "Номер заказа": "5",
    }


async def test_user_falls_back_to_login(api, cl):
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[attr(105, val(None, user={"name": "jdoe"}))]))
    assert (await cl.get_object(1)).attributes == {"Владелец": "jdoe"}


async def test_multi_value_attribute_joined(api, cl):
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[
        attr(102, val(referencedObject={"label": "QA"}), val(referencedObject={"label": "Dev"}), val(referencedObject={"label": "Ops"})),
    ]))
    assert (await cl.get_object(1)).attributes == {"Команда-получатель": "QA, Dev, Ops"}


async def test_empty_values_are_dropped(api, cl):
    """Пустые значения/пустые списки не попадают в attributes (ни ключа, ни «None»)."""
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[
        attr(100, val("A001")),
        attr(103),                                    # пустой список значений
        attr(104, val(None), val("", ""), val(None, None)),  # только пустое
        attr(101, val("Ожидает"), val(None)),         # пустое рядом с живым — живое остаётся
    ]))
    assert (await cl.get_object(1)).attributes == {"Name": "A001", "Статус": "Ожидает"}


async def test_attributes_null_or_missing(api, cl):
    api.get(f"{API}/object/1").respond(200, json={**entry(1), "attributes": None})
    api.get(f"{API}/object/2").respond(200, json={k: v for k, v in entry(2).items() if k != "attributes"})
    assert (await cl.get_object(1)).attributes == {}
    assert (await cl.get_object(2)).attributes == {}


async def test_bool_and_zero_values_stringified(api, cl):
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[
        attr(103, val(True)), attr(104, val(0)), attr(100, val(False, "Нет")),
    ]))
    assert (await cl.get_object(1)).attributes == {
        "Срок использования": "True", "Номер заказа": "0", "Name": "Нет"}


async def test_inline_type_attribute_meta_beats_type_lookup(api, cl):
    """В ответе с includeTypeAttributes имя берётся из objectTypeAttribute, id по типу не нужен."""
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[
        attr(999, val("x"), inline_meta={"id": 999, "name": "Inline"}),
    ]))
    assert (await cl.get_object(1)).attributes == {"Inline": "x"}


async def test_unknown_attribute_id_is_skipped(api, cl):
    api.get(f"{API}/object/1").respond(200, json=entry(1, attributes=[attr(424242, val("x")), attr(100, val("A"))]))
    assert (await cl.get_object(1)).attributes == {"Name": "A"}


async def test_missing_optional_fields_get_defaults(api, cl):
    api.get(f"{API}/object/1").respond(200, json={"id": 1, "objectType": {"id": TYPE_ID}, "attributes": []})
    obj = await cl.get_object(1)
    assert (obj.key, obj.label, obj.object_type, obj.object_type_id) == ("", "", "", TYPE_ID)


async def test_type_attributes_fetched_once_per_type(api, cl):
    api.get(f"{API}/iql/objects").respond(200, json=page([entry(1), entry(2), entry(3)]))
    await cl.fetch_objects()
    types_route = next(r for r in api.routes if "attributes" in str(r.pattern))
    assert types_route.call_count == 1


async def test_type_attributes_error_raises_insight_error(cl):
    with respx.mock(assert_all_called=False) as r:
        r.get(f"{API}/objecttype/{TYPE_ID}/attributes").respond(500, text="boom")
        r.get(f"{API}/object/1").respond(200, json=entry(1))
        with pytest.raises(InsightError, match=f"типа {TYPE_ID}.*500"):
            await cl.get_object(1)


# ---------- get_object ----------

async def test_get_object_found(api, cl):
    route = api.get(f"{API}/object/42").respond(200, json=entry(42, "A042"))
    obj = await cl.get_object(42)
    assert (obj.id, obj.label) == (42, "A042")
    assert route.call_count == 1


async def test_get_object_404_returns_none(api, cl):
    api.get(f"{API}/object/42").respond(404, json={"errorMessages": ["not found"]})
    assert await cl.get_object(42) is None


@pytest.mark.parametrize("status", [400, 401, 403, 500, 502, 503])
async def test_get_object_other_errors_raise(api, cl, status):
    api.get(f"{API}/object/42").respond(status, text="server says no")
    with pytest.raises(InsightError, match=str(status)):
        await cl.get_object(42)


# ---------- ошибки поиска / диагностики ----------

@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_search_http_errors(api, cl, status):
    api.get(f"{API}/iql/objects").respond(status, text="Unauthorized")
    with pytest.raises(InsightError) as ei:
        await cl.fetch_objects()
    assert str(status) in str(ei.value)
    assert "Unauthorized" in str(ei.value)


async def test_error_text_is_truncated(api, cl):
    api.get(f"{API}/iql/objects").respond(500, text="x" * 5000)
    with pytest.raises(InsightError) as ei:
        await cl.fetch_objects()
    assert len(str(ei.value)) < 400


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_errors_do_not_leak_credentials(api, make_client, caplog, status):
    caplog.set_level(logging.DEBUG)
    api.get(f"{API}/iql/objects").respond(status, text="Unauthorized")
    api.get(f"{API}/object/1").respond(status, text="Forbidden")
    for c in (make_client(insight_token=TOKEN), make_client(insight_username="svc", insight_password=PASSWORD)):
        for call in (c.fetch_objects(), c.get_object(1), c.count("q")):
            with pytest.raises(InsightError) as ei:
                await call
            text = str(ei.value) + repr(ei.value)
            assert TOKEN not in text and PASSWORD not in text
    assert TOKEN not in caplog.text and PASSWORD not in caplog.text
    basic = base64.b64encode(f"svc:{PASSWORD}".encode()).decode()
    assert basic not in caplog.text


async def test_network_errors_do_not_leak_token(api, cl):
    """ConnectError / таймаут: что бы ни вылетело, в тексте нет токена."""
    for exc in (httpx.ConnectError("connection refused"), httpx.ReadTimeout("timed out")):
        api.get(f"{API}/iql/objects").mock(side_effect=exc)
        with pytest.raises(InsightError) as ei:
            await cl.fetch_objects()
        assert TOKEN not in str(ei.value) + repr(ei.value)


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("")])
async def test_network_error_wrapped_in_insight_error(api, cl, exc):
    api.get(f"{API}/iql/objects").mock(side_effect=exc)
    with pytest.raises(InsightError) as ei:
        await cl.fetch_objects()
    assert type(exc).__name__ in str(ei.value)  # у ReadTimeout текст пуст — имя класса всё равно видно


async def test_invalid_json_wrapped_in_insight_error(api, cl):
    api.get(f"{API}/iql/objects").respond(200, text="<html>Login</html>")
    with pytest.raises(InsightError):
        await cl.fetch_objects()


async def test_malformed_entry_wrapped_in_insight_error(api, cl):
    api.get(f"{API}/iql/objects").respond(200, json=page([{"id": 1, "label": "x"}]))
    with pytest.raises(InsightError):
        await cl.fetch_objects()


async def test_get_raw_returns_json_and_passes_params(api, cl):
    route = api.get(f"{API}/objectschema/list").respond(200, json={"objectschemas": []})
    assert await cl.get("/objectschema/list", x="1") == {"objectschemas": []}
    assert params(route)["x"] == "1"


async def test_get_raw_error(api, cl):
    api.get(f"{API}/nope").respond(404, text="nothing here")
    with pytest.raises(InsightError, match=r"/nope: HTTP 404 nothing here"):
        await cl.get("/nope")


async def test_get_raw_absolute_url(api, cl):
    route = api.get(f"{BASE}/rest/api/2/serverInfo").respond(200, json=[1])
    assert await cl.get(f"{BASE}/rest/api/2/serverInfo") == [1]
    assert route.called


async def test_whoami_ok(api, cl):
    api.get(f"{BASE}/rest/api/2/myself").respond(200, json={"displayName": "Svc Account", "name": "svc"})
    assert await cl.whoami() == "Svc Account (svc)"


@pytest.mark.parametrize("status", [401, 403])
async def test_whoami_unauthorized_message(api, cl, status):
    api.get(f"{BASE}/rest/api/2/myself").respond(status, text="denied")
    msg = await cl.whoami()
    assert f"HTTP {status}" in msg and "не авторизован" in msg
    assert TOKEN not in msg


# ---------- запись: update_object ----------

def body(route) -> dict:
    return json.loads(route.calls.last.request.content)


async def test_update_plain_value(api, cl):
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Номер заказа": "17"})
    req = put.calls.last.request
    assert (req.method, str(req.url)) == ("PUT", f"{API}/object/5")
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert body(put) == {"objectTypeId": TYPE_ID, "attributes": [
        {"objectTypeAttributeId": 104, "objectAttributeValues": [{"value": "17"}]}]}


async def test_update_attribute_name_is_case_insensitive(api, cl):
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"номер ЗАКАЗА": "1"})
    assert body(put)["attributes"][0]["objectTypeAttributeId"] == 104


async def test_update_empty_value_clears_attribute(api, cl):
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Срок использования": None, "Номер заказа": ""})
    assert body(put)["attributes"] == [
        {"objectTypeAttributeId": 103, "objectAttributeValues": []},
        {"objectTypeAttributeId": 104, "objectAttributeValues": []},
    ]


async def test_update_status_translated_to_status_id(api, cl):
    status_route = api.get(f"{API}/config/statustype").respond(
        200, json=[{"id": 11, "name": "Используется"}, {"id": 12, "name": "Ожидает"}])
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Статус": "используется"})  # регистр не важен
    assert body(put)["attributes"] == [{"objectTypeAttributeId": 101, "objectAttributeValues": [{"value": "11"}]}]
    assert params(status_route)["objectSchemaId"] == "1"


async def test_status_list_cached_between_updates(api, cl):
    status_route = api.get(f"{API}/config/statustype").respond(200, json=[{"id": 12, "name": "Ожидает"}])
    api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Статус": "Ожидает"})
    await cl.update_object(5, TYPE_ID, {"Статус": "Ожидает"})
    assert status_route.call_count == 1


async def test_status_without_schema_id_has_no_params(api, make_client):
    c = make_client(InsightMapping(query="q", schema_id=None))
    route = api.get(f"{API}/config/statustype").respond(200, json=[{"id": 1, "name": "A"}])
    api.put(f"{API}/object/5").respond(200, json={})
    await c.update_object(5, TYPE_ID, {"Статус": "A"})
    assert "objectSchemaId" not in params(route)


async def test_update_unknown_status_raises_and_does_not_put(api, cl):
    api.get(f"{API}/config/statustype").respond(200, json=[{"id": 12, "name": "Ожидает"}])
    put = api.put(f"{API}/object/5").respond(200, json={})
    with pytest.raises(InsightError, match="нет статуса «Бред»"):
        await cl.update_object(5, TYPE_ID, {"Статус": "Бред"})
    assert not put.called


async def test_status_list_http_error(api, cl):
    api.get(f"{API}/config/statustype").respond(403, text="no")
    with pytest.raises(InsightError, match="статусы Insight.*403"):
        await cl.update_object(5, TYPE_ID, {"Статус": "Ожидает"})


async def test_update_clearing_status_needs_no_status_lookup(api, cl):
    status_route = api.get(f"{API}/config/statustype").respond(200, json=[])
    api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Статус": None})
    assert not status_route.called


async def test_update_reference_resolved_to_object_key(api, cl):
    search = api.get(f"{API}/iql/objects").respond(200, json=page([entry(9, "QA")]))
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Команда-получатель": "QA"})
    assert params(search)["iql"] == f'objectTypeId = {REF_TYPE_ID} AND Label = "QA"'
    assert body(put)["attributes"] == [{"objectTypeAttributeId": 102, "objectAttributeValues": [{"value": "ITAM-9"}]}]


async def test_update_reference_not_found(api, cl):
    api.get(f"{API}/iql/objects").respond(200, json=page([]))
    put = api.put(f"{API}/object/5").respond(200, json={})
    with pytest.raises(InsightError, match="не найден объект «Нет такой»"):
        await cl.update_object(5, TYPE_ID, {"Команда-получатель": "Нет такой"})
    assert not put.called


async def test_reference_label_quotes_are_escaped(api, cl):
    search = api.get(f"{API}/iql/objects").respond(200, json=page([entry(9, 'Team "A"')]))
    api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Команда-получатель": 'Team "A"'})
    assert params(search)["iql"] == f'objectTypeId = {REF_TYPE_ID} AND Label = "Team \\"A\\""'


async def test_reference_label_backslash_is_escaped(api, cl):
    search = api.get(f"{API}/iql/objects").respond(200, json=page([entry(9, "A\\B")]))
    api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Команда-получатель": "A\\B"})
    assert params(search)["iql"] == f'objectTypeId = {REF_TYPE_ID} AND Label = "A\\\\B"'


async def test_update_unknown_attribute_raises(api, cl):
    put = api.put(f"{API}/object/5").respond(200, json={})
    with pytest.raises(InsightError, match="нет атрибута «Левый»"):
        await cl.update_object(5, TYPE_ID, {"Левый": "x"})
    assert not put.called


async def test_update_optional_unknown_attribute_skipped(api, cl, caplog):
    caplog.set_level(logging.WARNING)
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Левый": "x", "Номер заказа": "3"}, optional={"Левый"})
    assert [a["objectTypeAttributeId"] for a in body(put)["attributes"]] == [104]
    assert "Левый" in caplog.text


async def test_update_all_skipped_sends_nothing(api, cl):
    put = api.put(f"{API}/object/5").respond(200, json={})
    await cl.update_object(5, TYPE_ID, {"Левый": "x"}, optional={"Левый"})
    await cl.update_object(5, TYPE_ID, {})
    assert not put.called


async def test_update_optional_only_applies_to_listed_names(api, cl):
    with pytest.raises(InsightError, match="«Другой»"):
        await cl.update_object(5, TYPE_ID, {"Левый": "x", "Другой": "y"}, optional={"Левый"})


async def test_update_without_type_id_raises(api, cl):
    with pytest.raises(InsightError, match="синхронизацию"):
        await cl.update_object(5, None, {"Номер заказа": "1"})


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 500, 503])
async def test_update_http_errors(api, cl, status):
    api.put(f"{API}/object/5").respond(status, text="rejected by insight")
    with pytest.raises(InsightError) as ei:
        await cl.update_object(5, TYPE_ID, {"Номер заказа": "1"})
    assert str(status) in str(ei.value) and "rejected by insight" in str(ei.value)
    assert TOKEN not in str(ei.value)


async def test_update_error_text_is_truncated(api, cl):
    api.put(f"{API}/object/5").respond(500, text="y" * 5000)
    with pytest.raises(InsightError) as ei:
        await cl.update_object(5, TYPE_ID, {"Номер заказа": "1"})
    assert len(str(ei.value)) < 400


async def test_update_network_error_does_not_leak_token(api, cl):
    api.put(f"{API}/object/5").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(InsightError, match="недоступен") as ei:
        await cl.update_object(5, TYPE_ID, {"Номер заказа": "1"})
    assert TOKEN not in str(ei.value)
