"""Простой серверов: свободные ПК опубликованных пулов и давность их последней выдачи."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core import clock
from app.services import idle
from tests.sync_fakes import add_booking

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: NOW.astimezone(clock.display_tz()).date())


def ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


@pytest.fixture
async def ctx(make_user, make_department, make_pool):
    dept = await make_department("QA")
    return dept, await make_user("u", department=dept), await make_pool("Main")


async def test_idle_counts_from_last_return_or_registration(session, ctx, make_computer):
    dept, user, pool = ctx
    never = await make_computer("A-never", pool, created_at=ago(30))
    returned = await make_computer("A-returned", pool, created_at=ago(90))
    await add_booking(session, returned, user, dept, status="returned", returned_at=ago(5))
    await add_booking(session, returned, user, dept, status="returned", returned_at=ago(12))  # берётся самая поздняя
    result = await idle.list_idle(session)
    assert result.count == 2
    assert [(s.name, s.idle_days) for s in result.items] == [("A-never", 30), ("A-returned", 5)]
    assert result.average_days == 18  # (30 + 5) / 2, округление


async def test_idle_takes_only_free_computers_of_published_pools(session, ctx, make_computer, make_pool):
    dept, user, pool = ctx
    hidden = await make_pool("Hidden", is_published=False)
    await make_computer("free", pool, created_at=ago(10))
    await make_computer("booked", pool, status="booked", created_at=ago(10))
    await make_computer("broken", pool, status="maintenance", created_at=ago(10))
    await make_computer("archived", pool, is_archived=True, created_at=ago(10))
    await make_computer("hidden-pool", hidden, created_at=ago(10))
    await make_computer("no-pool", None, created_at=ago(10))
    result = await idle.list_idle(session)
    assert [s.name for s in result.items] == ["free"]


async def test_idle_top_limit_and_sorting(session, ctx, make_computer):
    _, _, pool = ctx
    for i in range(idle.IDLE_TOP + 3):
        await make_computer(f"A{i:02d}", pool, created_at=ago(i + 1))
    result = await idle.list_idle(session)
    assert result.count == idle.IDLE_TOP + 3  # счётчик по всем, список — только самые долгие
    assert len(result.items) == idle.IDLE_TOP
    days = [s.idle_days for s in result.items]
    assert days == sorted(days, reverse=True) and days[0] == idle.IDLE_TOP + 3


async def test_idle_empty(session):
    result = await idle.list_idle(session)
    assert (result.count, result.average_days, result.items) == (0, 0, [])


async def test_idle_endpoint_admin_only(client, login, api, make_user, ctx, make_computer):
    _, _, pool = ctx
    await make_computer("A1", pool, created_at=ago(7))
    assert (await client.get(api("/admin/idle"))).status_code == 401
    login(await make_user("worker"))
    assert (await client.get(api("/admin/idle"))).status_code == 403
    login(await make_user("boss", role="admin"))
    r = await client.get(api("/admin/idle"))
    assert r.status_code == 200 and r.json()["count"] == 1 and r.json()["items"][0]["idle_days"] == 7
