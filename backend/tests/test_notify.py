"""Уведомления в Mattermost (входящий вебхук): выключено без URL, тело запроса, сбои не ломают вызывающий код."""
import json
import logging

import httpx
import pytest

from app.core.config import settings
from app.integrations.notify import notify

HOOK = "https://mm.example/hooks/abc"


@pytest.fixture
def hook(monkeypatch):
    monkeypatch.setattr(settings, "mattermost_webhook_url", HOOK)


@pytest.mark.parametrize("url", ["", None])
async def test_no_url_sends_nothing(respx_mock, monkeypatch, url):
    monkeypatch.setattr(settings, "mattermost_webhook_url", url)
    await notify("hello")
    assert len(respx_mock.calls) == 0  # любой HTTP-вызов упал бы на assert_all_mocked


async def test_posts_json_payload(respx_mock, hook, monkeypatch):
    monkeypatch.setattr(settings, "app_name", "HMS Rent")
    route = respx_mock.post(HOOK).respond(200, text="ok")
    await notify("ПК A001 забронирован: \"тест\" <b>")
    req = route.calls.last.request
    assert req.headers["content-type"] == "application/json"
    assert json.loads(req.content) == {
        "text": "ПК A001 забронирован: \"тест\" <b>", "username": "HMS Rent"}


@pytest.mark.parametrize("exc", [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("t")])
async def test_network_errors_are_swallowed_and_logged(respx_mock, hook, caplog, exc):
    respx_mock.post(HOOK).mock(side_effect=exc)
    with caplog.at_level(logging.WARNING, logger="app.integrations.notify"):
        await notify("x")  # не бросает
    assert "Mattermost недоступен" in caplog.text


@pytest.mark.parametrize("status", [400, 404, 500])
async def test_http_error_status_does_not_raise(respx_mock, hook, status):
    respx_mock.post(HOOK).respond(status)
    await notify("x")


async def test_non_http_errors_are_not_hidden(respx_mock, hook):
    """Ловим только httpx.HTTPError: программная ошибка не должна глотаться молча."""
    respx_mock.post(HOOK).mock(side_effect=RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        await notify("x")
