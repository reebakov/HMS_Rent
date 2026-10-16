"""Служебный CLI (python -m app.cli): создание/блокировка админов, смена пароля, список, push-pools, insight-check.

main() обёрнут в asyncio.run, а тесты живут в одном event loop с пулом asyncpg, поэтому корутины команд вызываем
напрямую (await), а диспетчер main() проверяем подменой asyncio.run.
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app import cli
from app.core.config import settings
from app.core.security import verify_password
from app.models import Computer, User, UserRole

BACKEND_DIR = Path(__file__).resolve().parents[1]
STRONG = "correct-horse-1"


@pytest.fixture
def typed(monkeypatch):
    """typed(*ответы) — что «введёт» пользователь на запросы getpass; лишний запрос роняет тест."""
    def _typed(*answers: str) -> list[str]:
        it = iter(answers)
        asked: list[str] = []

        def fake_getpass(prompt=""):
            asked.append(prompt)
            return next(it)
        monkeypatch.setattr(cli.getpass, "getpass", fake_getpass)
        return asked
    return _typed


async def _user(session, username: str) -> User | None:
    session.expire_all()
    return await session.scalar(select(User).where(User.username == username))


# ---------- ask_password ----------

def test_ask_password_accepts_ten_chars(typed):
    typed("a" * 10, "a" * 10)
    assert cli.ask_password() == "a" * 10


def test_ask_password_retries_on_short_and_mismatch(typed, capsys):
    asked = typed("a" * 9,               # слишком короткий -> повтор без подтверждения
                  STRONG, "other-pass-1",  # не совпали -> повтор
                  STRONG, STRONG)
    assert cli.ask_password() == STRONG
    out = capsys.readouterr().out
    assert "Слишком короткий пароль" in out and "Пароли не совпали" in out
    assert len(asked) == 5


# ---------- create-admin ----------

async def test_create_admin(session, typed, capsys):
    typed(STRONG, STRONG)
    await cli.create_admin("  Boss ", "Главный Босс")
    u = await _user(session, "boss")  # логин нормализован: trim + lower
    assert u.role == UserRole.admin.value and u.auth_source == "local" and u.is_active
    assert u.display_name == "Главный Босс"
    assert u.password_hash != STRONG and verify_password(STRONG, u.password_hash)
    assert not verify_password("wrong-password", u.password_hash)
    assert "Администратор «boss» создан" in capsys.readouterr().out


async def test_create_admin_default_display_name_is_username(session, typed):
    typed(STRONG, STRONG)
    await cli.create_admin("boss", None)
    assert (await _user(session, "boss")).display_name == "boss"


async def test_create_admin_duplicate_exits_without_asking_password(session, typed, make_user):
    old = await make_user("boss", role="user")
    asked = typed()  # getpass вызывать нельзя
    with pytest.raises(SystemExit) as e:
        await cli.create_admin("BOSS", None)
    assert "уже есть" in e.value.code and "set-password boss" in e.value.code
    assert asked == []
    assert (await _user(session, "boss")).password_hash == old.password_hash and old.role == "user"


async def test_create_admin_duplicate_of_sso_user_also_rejected(typed, make_user):
    await make_user("sso@corp.io", auth_source="bouncer", password=None)
    typed()
    with pytest.raises(SystemExit):
        await cli.create_admin("sso@corp.io", None)


async def test_create_admin_short_password_retried_then_saved(session, typed):
    typed("short", STRONG, STRONG)
    await cli.create_admin("boss", None)
    assert verify_password(STRONG, (await _user(session, "boss")).password_hash)


# ---------- set-password ----------

async def test_set_password_changes_hash(session, typed, make_user, capsys):
    await make_user("boss", role="admin", password="old-password-1")
    typed("new-password-1", "new-password-1")
    await cli.set_password("Boss")  # регистр не важен
    h = (await _user(session, "boss")).password_hash
    assert verify_password("new-password-1", h) and not verify_password("old-password-1", h)
    assert "Пароль обновлён" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["sso@corp.io", "ghost"])  # SSO-учётка и несуществующая
async def test_set_password_rejects_non_local_or_unknown(session, typed, make_user, name):
    await make_user("sso@corp.io", auth_source="bouncer", password=None)
    typed()  # пароль не спрашивается
    with pytest.raises(SystemExit) as e:
        await cli.set_password(name)
    assert "Локальная учётка не найдена" in e.value.code
    assert (await _user(session, "sso@corp.io")).password_hash is None  # SSO-учётке пароль не появился


# ---------- disable / enable ----------

async def test_disable_and_enable(session, make_user, capsys):
    await make_user("ivanov")
    await cli.set_active("ivanov", False)
    assert (await _user(session, "ivanov")).is_active is False
    assert "заблокирован" in capsys.readouterr().out
    await cli.set_active("IVANOV", True)
    assert (await _user(session, "ivanov")).is_active is True
    assert "активен" in capsys.readouterr().out


async def test_set_active_unknown_user_exits():
    with pytest.raises(SystemExit) as e:
        await cli.set_active("nobody", False)
    assert e.value.code == "Пользователь не найден"


# ---------- users ----------

async def test_list_users_output(make_user, session, capsys):
    await make_user("zed", role="user")
    await make_user("boss", role="admin", last_login_at=datetime(2025, 3, 9, 14, 5, tzinfo=timezone.utc))
    off = await make_user("alice", role="user", auth_source="bouncer", password=None)
    off.is_active = False
    await session.commit()
    await cli.list_users()
    lines = capsys.readouterr().out.splitlines()
    assert [ln.split()[0] for ln in lines] == ["boss", "alice", "zed"]  # сначала по роли (admin < user), затем по логину
    assert "local" in lines[0] and "admin" in lines[0] and "on" in lines[0] and "09.03.2025 14:05" in lines[0]
    assert "bouncer" in lines[1] and "OFF" in lines[1] and "вход: —" in lines[1]
    assert "вход: —" in lines[2]


async def test_list_users_empty(capsys):
    await cli.list_users()
    assert capsys.readouterr().out == ""


# ---------- push-pools ----------

async def test_push_pools_marks_only_pooled_active_computers(session, make_pool, make_computer, capsys):
    pool = await make_pool("P")
    await make_computer("A1", pool=pool)
    await make_computer("A2", pool=pool, is_archived=True)
    await make_computer("A3")  # без пула
    await cli.push_pools()
    session.expire_all()
    flags = {x.name: x.writeback_pending for x in (await session.scalars(select(Computer))).all()}
    assert flags == {"A1": True, "A2": False, "A3": False}
    assert "поставлено ПК: 1" in capsys.readouterr().out


# ---------- insight-check ----------

@pytest.fixture
def jira(respx_mock, monkeypatch):
    """Фейковый Jira/Insight под mock-маппинг (config/insight_mapping.mock.yaml)."""
    monkeypatch.setattr(settings, "jira_url", "https://jira.test")
    monkeypatch.setattr(settings, "insight_token", "")
    monkeypatch.setattr(settings, "insight_username", "")
    monkeypatch.setattr(settings, "insight_api", "iql")
    monkeypatch.setattr(settings, "insight_mapping_file", "config/insight_mapping.mock.yaml")
    api = "https://jira.test/rest/insight/1.0"
    respx_mock.get("https://jira.test/rest/api/2/myself").respond(json={"displayName": "Bot", "name": "bot"})
    respx_mock.get(f"{api}/objectschema/list").respond(json={"objectschemas": [{"id": 1, "name": "IT", "objectCount": 3}]})
    respx_mock.get(f"{api}/objectschema/1/objecttypes/flat").respond(
        json=[{"id": 21, "name": "Компьютер", "objectCount": 2}])
    respx_mock.get(f"{api}/config/statustype").respond(json=[{"id": 1, "name": "Свободен"}])
    respx_mock.get(f"{api}/objecttype/21/attributes").respond(
        json=[{"id": 100, "name": "Name"}, {"id": 101, "name": "Статус"}])

    def entry(oid, label, status):
        attrs = [{"objectTypeAttributeId": 100, "objectAttributeValues": [{"value": label}]}]
        if status:
            attrs.append({"objectTypeAttributeId": 101, "objectAttributeValues": [{"status": {"name": status}}]})
        return {"id": oid, "objectKey": f"ITAM-{oid}", "label": label, "objectType": {"id": 21, "name": "Компьютер"},
                "attributes": attrs}

    def search(entries, total):
        return respx_mock.get(f"{api}/iql/objects").respond(json={"objectEntries": entries, "totalFilterCount": total})
    return type("J", (), {"entry": staticmethod(entry), "search": staticmethod(search), "mock": respx_mock})


async def test_insight_check_overview(jira, capsys):
    jira.search([jira.entry(1, "A001", "Свободен")], 1)
    await cli.insight_check(5, None, None)
    out = capsys.readouterr().out
    assert "Учётка: Bot (bot)" in out and "id=1" in out and "IT" in out
    assert "Типы объектов схемы 1" in out and "Статусы: Свободен" in out
    assert "Найдено объектов: 1" in out
    assert "— ITAM-1 A001 [Компьютер]" in out and "«Свободен» → available" in out
    assert "⚠ В Insight нет атрибутов из маппинга" in out  # в фейке нет «Процессор», «ОЗУ» и т.д.


async def test_insight_check_custom_query_is_sent(jira, capsys):
    route = jira.search([], 0)
    await cli.insight_check(5, 'objectType = "X"', None)
    assert all(r.request.url.params["iql"] == 'objectType = "X"' for r in route.calls)
    assert "Запрос ничего не вернул" in capsys.readouterr().out


async def test_insight_check_breakdown(jira, capsys):
    jira.search([jira.entry(1, "A001", "Свободен"), jira.entry(2, "A002", None)], 2)
    await cli.insight_check(5, None, "Статус")
    out = capsys.readouterr().out
    assert "Разбивка по «Статус»" in out and "Свободен: 2" in out and "(пусто)" in out
    assert "Схемы объектов" not in out  # в режиме разбивки обзор схем не печатается


async def test_insight_check_closes_client_on_error(jira):
    jira.mock.get("https://jira.test/rest/insight/1.0/iql/objects").respond(500, text="boom")
    from app.integrations.insight.base import InsightError
    with pytest.raises(InsightError):
        await cli.insight_check(5, None, None)


# ---------- main(): разбор аргументов и диспетчеризация ----------

@pytest.fixture
def run_main(monkeypatch):
    """run_main(*argv) -> корутина, которую main() передал в asyncio.run (сама не выполняется)."""
    def _run(*argv: str):
        got = []
        monkeypatch.setattr(cli.asyncio, "run", got.append)
        monkeypatch.setattr(sys, "argv", ["cli", *argv])
        cli.main()
        return got[0]
    return _run


@pytest.mark.parametrize("argv,func,args", [
    (["create-admin", "boss", "--name", "Босс"], "create_admin", {"username": "boss", "name": "Босс"}),
    (["create-admin", "boss"], "create_admin", {"username": "boss", "name": None}),
    (["set-password", "boss"], "set_password", {"username": "boss"}),
    (["disable", "boss"], "set_active", {"username": "boss", "active": False}),
    (["enable", "boss"], "set_active", {"username": "boss", "active": True}),
    (["users"], "list_users", {}),
    (["push-pools"], "push_pools", {}),
    (["insight-check"], "insight_check", {"sample": 5, "query": None, "breakdown": None}),
    (["insight-check", "--sample", "2", "--query", "q", "--breakdown", "Type"], "insight_check",
     {"sample": 2, "query": "q", "breakdown": "Type"}),
])
def test_main_dispatch(run_main, argv, func, args):
    coro = run_main(*argv)
    try:
        assert coro.cr_code.co_name == func
        assert coro.cr_frame.f_locals == args
    finally:
        coro.close()


@pytest.mark.parametrize("argv", [[], ["bogus"], ["create-admin"], ["insight-check", "--sample", "x"]])
def test_main_bad_usage_exits_with_code_2(run_main, argv, capsys):
    with pytest.raises(SystemExit) as e:
        run_main(*argv)
    assert e.value.code == 2 and capsys.readouterr().err


async def test_main_users_end_to_end_in_subprocess(make_user):
    """Настоящий запуск `python -m app.cli users` (свой event loop, DATABASE_URL из окружения)."""
    await make_user("boss", role="admin")
    r = subprocess.run([sys.executable, "-m", "app.cli", "users"], cwd=BACKEND_DIR, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("boss") and "local" in r.stdout and "admin" in r.stdout
