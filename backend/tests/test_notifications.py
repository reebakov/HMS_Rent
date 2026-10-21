"""Колокольчик: хранение уведомлений (services/notifications.py) и маршруты /notifications."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.errors import NotFound
from app.db.session import SessionLocal
from app.models import Notification, NotificationKind, UserRole
from app.services import notifications


@pytest_asyncio.fixture
async def env(session, make_department, make_user):
    dept = await make_department("QA")
    return SimpleNamespace(
        owner=await make_user("owner", department=dept), other=await make_user("other", department=dept),
        admin=await make_user("boss", role=UserRole.admin.value),
    )


async def put(session, user, title="Событие", *, read=False, **kw) -> Notification:
    notifications.add(session, user.id, NotificationKind.vm_ready, title, "текст")
    await session.commit()
    note = (await session.scalars(select(Notification).order_by(Notification.id.desc()))).first()
    if read:
        await notifications.mark_read(session, user, note.id)
    return note


async def test_list_newest_first_with_unread_count(session, env):
    first, second = await put(session, env.owner, "первое"), await put(session, env.owner, "второе")
    await notifications.mark_read(session, env.owner, first.id)
    rows, unread = await notifications.list_for(session, env.owner)
    assert [n.title for n in rows] == ["второе", "первое"] and unread == 1
    assert second.read_at is None


async def test_list_is_limited_but_unread_counts_everything(session, env):
    for i in range(notifications.LIST_LIMIT + 5):
        notifications.add(session, env.owner.id, NotificationKind.vm_ready, f"№{i}")
    await session.commit()
    rows, unread = await notifications.list_for(session, env.owner)
    assert len(rows) == notifications.LIST_LIMIT and unread == notifications.LIST_LIMIT + 5
    assert rows[0].title == f"№{notifications.LIST_LIMIT + 4}"


async def test_list_has_only_own(session, env):
    await put(session, env.other, "чужое")
    assert await notifications.list_for(session, env.owner) == ([], 0)


async def test_mark_read_is_idempotent(session, env):
    note = await put(session, env.owner)
    await notifications.mark_read(session, env.owner, note.id)
    stamp = (await session.get(Notification, note.id, populate_existing=True)).read_at
    assert stamp is not None
    await notifications.mark_read(session, env.owner, note.id)
    assert (await session.get(Notification, note.id, populate_existing=True)).read_at == stamp


async def test_mark_read_foreign_or_unknown_is_not_found(session, env):
    note = await put(session, env.other)
    for nid in (note.id, 9999):
        with pytest.raises(NotFound):
            await notifications.mark_read(session, env.owner, nid)
    assert (await session.get(Notification, note.id, populate_existing=True)).read_at is None


async def test_mark_all_read_touches_only_own(session, env):
    await put(session, env.owner), await put(session, env.owner), await put(session, env.other)
    await notifications.mark_all_read(session, env.owner)
    assert (await notifications.list_for(session, env.owner))[1] == 0
    assert (await notifications.list_for(session, env.other))[1] == 1


async def test_prune_removes_only_old(session, env):
    old, fresh = await put(session, env.owner, "старое"), await put(session, env.owner, "свежее")
    old.created_at = fresh.created_at - timedelta(days=notifications.KEEP_DAYS + 1)
    await session.commit()
    await notifications.prune(session)
    async with SessionLocal() as s:
        assert [n.title for n in await s.scalars(select(Notification))] == ["свежее"]


# ---------- маршруты ----------

@pytest.mark.parametrize("method, path", [("get", "/notifications"), ("post", "/notifications/read-all"),
                                          ("post", "/notifications/1/read")])
async def test_anonymous_gets_401(client, api, method, path):
    assert (await getattr(client, method)(api(path))).status_code == 401


async def test_api_list_and_read(client, login, api, session, env):
    note = await put(session, env.owner, "ВМ A1001 готова")
    await put(session, env.other, "чужое")
    login(env.owner)
    r = await client.get(api("/notifications"))
    assert r.status_code == 200
    body = r.json()
    assert body["unread"] == 1 and [n["title"] for n in body["items"]] == ["ВМ A1001 готова"]
    assert body["items"][0]["kind"] == "vm_ready" and body["items"][0]["read_at"] is None

    assert (await client.post(api(f"/notifications/{note.id}/read"))).status_code == 204
    body = (await client.get(api("/notifications"))).json()
    assert body["unread"] == 0 and body["items"][0]["read_at"] is not None


async def test_api_read_foreign_is_404(client, login, api, session, env):
    note = await put(session, env.other)
    login(env.owner)
    assert (await client.post(api(f"/notifications/{note.id}/read"))).status_code == 404


async def test_api_read_all(client, login, api, session, env):
    await put(session, env.owner), await put(session, env.owner)
    login(env.owner)
    assert (await client.post(api("/notifications/read-all"))).status_code == 204
    assert (await client.get(api("/notifications"))).json()["unread"] == 0
