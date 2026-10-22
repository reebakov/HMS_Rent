"""CLI sd-check (app/cli.py): проверка Service Desk — какие поля у типов заявок обязательны.

request_type_fields подменяем фейком: сети и Jira нет. Корутину вызываем напрямую (см. пояснение в test_cli.py),
диспетчер main() — подменой asyncio.run.
"""
import sys

import pytest

from app import cli
from app.core.config import settings
from app.integrations import servicedesk
from app.integrations.servicedesk import ServiceDeskError

SUMMARY = {"fieldId": "summary", "name": "Тема", "required": True}
DESCRIPTION = {"fieldId": "description", "name": "Описание", "required": False}
HINT = "Портал заполняет summary и description"


@pytest.fixture
def sd_fields(monkeypatch):
    """sd_fields({тип: список полей | исключение}) -> список id типов, по которым ходила команда."""
    def _set(by_type: dict) -> list[int]:
        asked: list[int] = []

        async def fake(type_id):
            asked.append(type_id)
            result = by_type[type_id]
            if isinstance(result, Exception):
                raise result
            return result
        monkeypatch.setattr(servicedesk, "request_type_fields", fake)
        return asked
    return _set


def lines_of(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


async def test_sd_check_prints_headers_fields_and_marks_required(sd_fields, capsys):
    asked = sd_fields({1248: [SUMMARY, DESCRIPTION], 1252: [{"fieldId": "customfield_10500", "name": "Инвентарный №",
                                                             "required": True}]})
    await cli.sd_check()
    out = lines_of(capsys)
    assert asked == [1248, 1252]  # сначала «Проблема», потом «Возврат»
    assert out[0] == f"Service Desk: {settings.sd_jira_url}, id={settings.sd_service_desk_id}"
    assert out.index("Проблема (1248):") < out.index("Возврат (1252):")
    by_id = {line.split()[0]: line for line in out if line.startswith("  ")}
    assert by_id["summary"].endswith("Тема ОБЯЗАТЕЛЬНО")
    assert "ОБЯЗАТЕЛЬНО" not in by_id["description"] and "Описание" in by_id["description"]
    assert "Инвентарный №" in by_id["customfield_10500"] and "ОБЯЗАТЕЛЬНО" in by_id["customfield_10500"]
    assert HINT in out[-1]  # подсказка — последней строкой


async def test_sd_check_uses_configured_type_ids(sd_fields, capsys, monkeypatch):
    monkeypatch.setattr(settings, "sd_request_type_problem", 11)
    monkeypatch.setattr(settings, "sd_request_type_return", 22)
    asked = sd_fields({11: [SUMMARY], 22: []})
    await cli.sd_check()
    out = capsys.readouterr().out
    assert asked == [11, 22] and "Проблема (11):" in out and "Возврат (22):" in out


async def test_sd_check_field_without_required_flag_is_optional(sd_fields, capsys):
    sd_fields({1248: [{"fieldId": "priority", "name": "Приоритет"}], 1252: []})
    await cli.sd_check()
    assert "ОБЯЗАТЕЛЬНО" not in capsys.readouterr().out


async def test_sd_check_error_on_first_type_continues_with_second(sd_fields, capsys):
    asked = sd_fields({1248: ServiceDeskError("403: нет доступа"), 1252: [SUMMARY]})
    await cli.sd_check()  # ошибка типа не роняет команду
    out = capsys.readouterr().out
    assert asked == [1248, 1252]
    assert "Проблема (1248): ОШИБКА — 403: нет доступа" in out
    assert "\nВозврат (1252):\n" in out and "summary" in out  # второй тип проверен как обычно
    assert HINT in out


async def test_sd_check_error_on_second_type_keeps_first_result(sd_fields, capsys):
    sd_fields({1248: [SUMMARY], 1252: ServiceDeskError("404")})
    await cli.sd_check()
    out = capsys.readouterr().out
    assert "\nПроблема (1248):\n" in out and "summary" in out
    assert "Возврат (1252): ОШИБКА — 404" in out and HINT in out


async def test_sd_check_both_types_fail(sd_fields, capsys):
    sd_fields({1248: ServiceDeskError("Service Desk не настроен"), 1252: ServiceDeskError("Service Desk не настроен")})
    await cli.sd_check()
    out = capsys.readouterr().out
    assert out.count("ОШИБКА — Service Desk не настроен") == 2 and HINT in out


async def test_sd_check_not_configured_reports_error_for_both_types(capsys):
    """Без подмены: SD_TOKEN не задан -> _client() кидает ServiceDeskError, команда печатает его для обоих типов."""
    assert not settings.sd_token and not settings.sd_username
    await cli.sd_check()
    out = capsys.readouterr().out
    assert out.count("ОШИБКА — Service Desk не настроен") == 2 and HINT in out


def test_main_dispatches_sd_check(monkeypatch):
    got = []
    monkeypatch.setattr(cli.asyncio, "run", got.append)
    monkeypatch.setattr(sys, "argv", ["cli", "sd-check"])
    cli.main()
    coro = got[0]
    try:
        assert coro.cr_code.co_name == "sd_check" and coro.cr_frame.f_locals == {}
    finally:
        coro.close()


@pytest.fixture
def sd_issue(monkeypatch):
    """sd_issue(transitions=..., details=...) — результат или исключение для каждого из двух чтений."""
    def _set(transitions, details):
        async def fake_transitions(key):
            if isinstance(transitions, Exception):
                raise transitions
            return transitions

        async def fake_details(key):
            if isinstance(details, Exception):
                raise details
            return details
        monkeypatch.setattr(servicedesk, "transitions", fake_transitions)
        monkeypatch.setattr(servicedesk, "get_details", fake_details)
    return _set


async def test_sd_transitions_prints_transitions_and_history(sd_issue, capsys):
    sd_issue([{"id": "151", "name": "Done", "to": {"name": "Done"}}, {"id": "171", "name": "Hold", "to": {"name": "To Do"}}],
             servicedesk.SdDetails(taken=True, resolution="Rejected"))
    await cli.sd_transitions("DR-1")
    out = capsys.readouterr().out
    assert "Задача DR-1" in out and "151  Done -> Done" in out and "171  Hold -> To Do" in out
    assert "перехода в Done нет" not in out
    assert "История читается: брали в работу — да, резолюция — Rejected" in out


async def test_sd_transitions_warns_when_done_is_unavailable(sd_issue, capsys):
    sd_issue([{"id": "171", "name": "Hold", "to": {"name": "To Do"}}], servicedesk.SdDetails(taken=False, resolution=None))
    await cli.sd_transitions("DR-1")
    out = capsys.readouterr().out
    assert "перехода в Done нет" in out and "брали в работу — нет, резолюция — —" in out


async def test_sd_transitions_reports_errors_separately(sd_issue, capsys):
    sd_issue(ServiceDeskError("Service Desk 403: нет прав"), ServiceDeskError("Service Desk 404: нет задачи"))
    await cli.sd_transitions("DR-1")
    out = capsys.readouterr().out
    assert "Переходы: ОШИБКА — Service Desk 403: нет прав" in out
    assert "История и резолюция: ОШИБКА — Service Desk 404: нет задачи" in out


def test_main_dispatches_sd_transitions(monkeypatch):
    got = []
    monkeypatch.setattr(cli.asyncio, "run", got.append)
    monkeypatch.setattr(sys, "argv", ["cli", "sd-transitions", "DR-7"])
    cli.main()
    coro = got[0]
    try:
        assert coro.cr_code.co_name == "sd_transitions" and coro.cr_frame.f_locals == {"issue_key": "DR-7"}
    finally:
        coro.close()
