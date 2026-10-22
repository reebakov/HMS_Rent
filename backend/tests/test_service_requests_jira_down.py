"""Сквозные проверки: Jira Service Desk недоступна, сервис и API ведут себя предсказуемо.

Работает настоящий клиент app.integrations.servicedesk (сеть заменена respx); раньше сырые исключения httpx доходили
до сервиса: создание заявки отвечало 500, обновление статусов падало на первой же заявке.
"""
import httpx
import pytest
import respx

from app.core.config import settings
from app.core.errors import DomainError
from app.services import service_requests as svc

from .test_service_requests import add_req, env, fresh, rows  # noqa: F401  (env — фикстура)

API = "https://jira.test/rest/servicedeskapi"


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for k, v in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="", sd_password="",
                     sd_service_desk_id=54, sd_request_type_problem=1248, sd_request_type_return=1252,
                     sd_raise_on_behalf=True, sd_return_on_return=True, sd_verify_ssl=True).items():
        monkeypatch.setattr(settings, k, v)


@pytest.fixture
def jira():
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("")], ids=["connect", "timeout"])
async def test_create_problem_jira_down_is_domain_error(session, env, jira, exc):  # noqa: F811
    jira.post(f"{API}/request").mock(side_effect=exc)
    with pytest.raises(DomainError, match="Не удалось создать заявку: Service Desk недоступен"):
        await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="не включается")
    assert await rows() == []  # заявка, которую Jira не приняла, не сохраняется


async def test_get_with_comments_jira_down_is_domain_error(session, env, jira):  # noqa: F811
    req = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    jira.get(f"{API}/request/HMS-1").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(DomainError, match="^Service Desk недоступен$"):
        await svc.get_with_comments(session, env.owner, req.id)


async def test_add_comment_jira_down_is_domain_error(session, env, jira):  # noqa: F811
    req = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    jira.post(f"{API}/request/HMS-1/comment").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(DomainError, match="Не удалось отправить сообщение: Service Desk недоступен"):
        await svc.add_comment(session, env.owner, req.id, "спасибо")


async def test_refresh_open_survives_failure_of_one_request(session, env, jira):  # noqa: F811
    broken = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    healthy = await add_req(session, env.owner, booking=env.booking, key="HMS-2")
    jira.get(f"{API}/request/HMS-1").mock(side_effect=httpx.ConnectError("refused"))
    jira.get(f"{API}/request/HMS-2").respond(200, json={"currentStatus": {"status": "Решено", "statusCategory": "DONE"}})
    jira.get("https://jira.test/rest/api/2/issue/HMS-2").respond(200, json={"fields": {"resolution": {"name": "Done"}}})
    await svc.refresh_open(session)  # не бросает: одна недоступная заявка не мешает остальным
    assert (await fresh(healthy.id)).status == "Решено"
    saved = await fresh(broken.id)
    assert saved.status is None and saved.last_checked_at is not None  # проверена, повтор через 2 минуты


async def test_return_request_jira_down_keeps_error_and_does_not_raise(session, env, jira):  # noqa: F811
    jira.post(f"{API}/request").mock(side_effect=httpx.ConnectError("refused"))
    await svc.create_return(session, env.booking.id, env.owner)
    (req,) = await rows()
    assert req.kind == "return" and req.issue_key is None and "недоступен" in req.error


async def test_api_create_request_jira_down_is_client_error(client, login, api, env, jira):  # noqa: F811
    jira.post(f"{API}/request").mock(side_effect=httpx.ConnectError("refused"))
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "не включается"})
    assert r.status_code == 400 and "Не удалось создать заявку" in r.json()["detail"]


# ---------- Jira ответила ошибкой: тело ответа не должно попасть к пользователю ----------

SECRET_BODY = "customfield_10042: internal secret detail"


async def test_api_create_request_jira_error_body_not_exposed(client, login, api, env, jira, caplog):  # noqa: F811
    jira.post(f"{API}/request").respond(400, json={"errorMessage": SECRET_BODY})
    login(env.owner)
    r = await client.post(api("/requests"), json={"booking_id": env.booking.id, "message": "не включается"})
    assert r.status_code == 400
    assert r.json()["detail"] == "Не удалось создать заявку: Service Desk отклонил запрос, попробуйте позже"
    assert SECRET_BODY not in r.text
    assert SECRET_BODY in caplog.text  # подробности остались в логе


async def test_get_with_comments_jira_error_body_not_exposed(session, env, jira):  # noqa: F811
    req = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    jira.get(f"{API}/request/HMS-1").respond(500, text=SECRET_BODY)
    with pytest.raises(DomainError) as e:
        await svc.get_with_comments(session, env.owner, req.id)
    assert str(e.value) == "Service Desk отклонил запрос, попробуйте позже" and SECRET_BODY not in str(e.value)


async def test_return_request_jira_error_hides_details_from_user(session, env, jira, caplog):  # noqa: F811
    jira.post(f"{API}/request").respond(400, json={"errorMessage": SECRET_BODY})
    await svc.create_return(session, env.booking.id, env.owner)
    (req,) = await rows()
    # error показывается сотруднику в карточке заявки: тело ответа Jira туда не попадает, остаётся в логе
    assert req.error == "Service Desk отклонил запрос, попробуйте позже" and SECRET_BODY not in req.error
    assert SECRET_BODY in caplog.text


async def test_refresh_open_without_rest_access_keeps_status_of_closed_task(session, env, jira):  # noqa: F811
    """REST Jira закрыт для сервисной учётки (403): статус из Service Desk API всё равно сохраняется."""
    req = await add_req(session, env.owner, booking=env.booking, key="HMS-3")
    jira.get(f"{API}/request/HMS-3").respond(200, json={"currentStatus": {"status": "Решено", "statusCategory": "DONE"}})
    jira.get("https://jira.test/rest/api/2/issue/HMS-3").respond(403, json={"errorMessages": ["нет прав"]})
    await svc.refresh_open(session)
    saved = await fresh(req.id)
    assert (saved.status, saved.resolution, saved.customer_status) == ("Решено", None, "Решено")
