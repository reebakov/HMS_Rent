"""Пулы выдачи (services/pools.py) на реальной БД: assign, delete_pool, pool_stats, visible_pool_ids."""
import pytest
from sqlalchemy import func, select

from app.core.errors import Conflict, NotFound
from app.models import AssetEvent, Computer, Department, EventType, Pool, UserRole
from app.models.pool import pool_departments
from app.services import pools, runtime
from app.services.runtime import RuntimeConfig
from tests.sync_fakes import add_booking, events_of, reload_computers

ADMIN = UserRole.admin.value


def set_writeback(monkeypatch, value: bool):
    monkeypatch.setattr(runtime, "_cache", (0.0, RuntimeConfig(insight_writeback=value)))


@pytest.fixture
async def admin(make_user):
    return await make_user("boss", role=ADMIN)


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# ---------- assign: выбор ПК ----------

async def test_assign_by_computer_ids(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    a, b, c = await make_computer("A1"), await make_computer("A2"), await make_computer("A3")
    res = await pools.assign(session, admin, pool.id, computer_ids=[a.id, b.id])
    assert res == {"updated": 2, "not_found": []}
    comps = await reload_computers(session)
    assert (comps["A1"].pool_id, comps["A2"].pool_id, comps["A3"].pool_id) == (pool.id, pool.id, None)


async def test_assign_by_ids_ignores_unknown_ids(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    a = await make_computer("A1")
    res = await pools.assign(session, admin, pool.id, computer_ids=[a.id, 9999])
    assert res == {"updated": 1, "not_found": []}  # по id «не найден» не сообщается: список only для имён


async def test_assign_by_names_case_and_separators(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    for n in ("A24", "A432", "A434", "A442", "A500"):
        await make_computer(n)
    res = await pools.assign(session, admin, pool.id, names="a24, A432\nA434;  a442")
    assert res == {"updated": 4, "not_found": []}
    comps = await reload_computers(session)
    assert {n for n, c in comps.items() if c.pool_id == pool.id} == {"A24", "A432", "A434", "A442"}
    assert comps["A500"].pool_id is None


async def test_assign_by_insight_key(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1", insight_key="ITAM-101")
    await make_computer("A2", insight_key="ITAM-102")
    res = await pools.assign(session, admin, pool.id, names="itam-101")
    assert res == {"updated": 1, "not_found": []}
    comps = await reload_computers(session)
    assert comps["A1"].pool_id == pool.id and comps["A2"].pool_id is None


async def test_assign_names_dupes_collapse_and_not_found_listed(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1")
    res = await pools.assign(session, admin, pool.id, names="A1 a1 A1, Ghost; ghost, ZZ9")
    # дубли схлопнуты, ненайденные — в нижнем регистре, в порядке ввода
    assert res == {"updated": 1, "not_found": ["ghost", "zz9"]}
    assert await count(session, AssetEvent) == 1


async def test_assign_computer_ids_take_precedence_over_names(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    a, b = await make_computer("A1"), await make_computer("A2")
    res = await pools.assign(session, admin, pool.id, computer_ids=[a.id], names="A2")
    assert res["updated"] == 1
    comps = await reload_computers(session)
    assert comps["A1"].pool_id == pool.id and comps["A2"].pool_id is None


@pytest.mark.parametrize("kw", [{}, {"names": ""}, {"names": " ,;\n "}, {"computer_ids": []}, {"names": None}])
async def test_assign_empty_input_is_noop(session, admin, make_pool, make_computer, kw):
    pool = await make_pool("Main")
    await make_computer("A1")
    assert await pools.assign(session, admin, pool.id, **kw) == {"updated": 0, "not_found": []}
    assert (await reload_computers(session))["A1"].pool_id is None
    assert await count(session, AssetEvent) == 0


async def test_assign_unknown_pool_raises_not_found(session, admin, make_computer):
    comp = await make_computer("A1")
    with pytest.raises(NotFound, match="Пул не найден"):
        await pools.assign(session, admin, 999, computer_ids=[comp.id])
    assert (await reload_computers(session))["A1"].pool_id is None


async def test_assign_unknown_pool_checked_even_for_empty_input(session, admin):
    with pytest.raises(NotFound):
        await pools.assign(session, admin, 999, names="")


async def test_assign_skips_archived_computers(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    arch = await make_computer("A1", is_archived=True)
    by_ids = await pools.assign(session, admin, pool.id, computer_ids=[arch.id])
    by_name = await pools.assign(session, admin, pool.id, names="A1")
    assert by_ids == {"updated": 0, "not_found": []}
    assert by_name == {"updated": 0, "not_found": ["a1"]}  # архивный для админа «не найден»
    comp = (await reload_computers(session))["A1"]
    assert comp.pool_id is None and not comp.writeback_pending
    assert await count(session, AssetEvent) == 0


# ---------- assign: снятие, перенос, события ----------

async def test_assign_none_removes_from_pool(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    a, b = await make_computer("A1", pool), await make_computer("A2")
    res = await pools.assign(session, admin, None, computer_ids=[a.id, b.id])
    assert res == {"updated": 1, "not_found": []}  # A2 и так без пула
    comps = await reload_computers(session)
    assert comps["A1"].pool_id is None
    assert [e.message for e in await events_of(session, a)] == ["Пул: Main → —"]
    assert await events_of(session, b) == []


async def test_assign_already_in_pool_is_not_counted_and_no_event(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    comp = await make_computer("A1", pool, writeback_pending=False)
    res = await pools.assign(session, admin, pool.id, computer_ids=[comp.id])
    assert res == {"updated": 0, "not_found": []}
    assert await events_of(session, comp) == []
    assert not (await reload_computers(session))["A1"].writeback_pending


async def test_assign_already_in_pool_by_name_is_found_not_missing(session, admin, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1", pool)
    res = await pools.assign(session, admin, pool.id, names="A1")
    assert res == {"updated": 0, "not_found": []}


async def test_assign_event_text_actor_and_type(session, admin, make_pool, make_computer):
    old, new = await make_pool("Old"), await make_pool("New")
    moved, fresh = await make_computer("A1", old), await make_computer("A2")
    await pools.assign(session, admin, new.id, computer_ids=[moved.id, fresh.id])
    (ev_moved,), (ev_fresh,) = await events_of(session, moved), await events_of(session, fresh)
    assert ev_moved.message == "Пул: Old → New" and ev_fresh.message == "Пул: — → New"
    for ev in (ev_moved, ev_fresh):
        assert ev.event_type == EventType.admin_update and ev.actor_id == admin.id


@pytest.mark.parametrize("flag", [True, False])
async def test_assign_sets_writeback_pending_per_runtime(session, admin, make_pool, make_computer, monkeypatch, flag):
    set_writeback(monkeypatch, flag)
    pool = await make_pool("Main")
    comp = await make_computer("A1")
    await pools.assign(session, admin, pool.id, computer_ids=[comp.id])
    assert (await reload_computers(session))["A1"].writeback_pending is flag


async def test_assign_none_sets_writeback_pending_too(session, admin, make_pool, make_computer, monkeypatch):
    set_writeback(monkeypatch, True)
    pool = await make_pool("Main")
    comp = await make_computer("A1", pool)
    await pools.assign(session, admin, None, computer_ids=[comp.id])
    assert (await reload_computers(session))["A1"].writeback_pending is True


async def test_assign_booked_computer_can_be_moved(session, admin, make_pool, make_computer, make_department):
    """Бронь не блокирует смену пула (блокирует только удаление пула)."""
    old, new = await make_pool("Old"), await make_pool("New")
    dept = await make_department("QA")
    comp = await make_computer("A1", old, status="booked")
    await add_booking(session, comp, admin, dept)
    assert (await pools.assign(session, admin, new.id, computer_ids=[comp.id]))["updated"] == 1


# ---------- delete_pool ----------

async def test_delete_pool_not_found(session):
    with pytest.raises(NotFound, match="Пул не найден"):
        await pools.delete_pool(session, 999)


async def test_delete_pool_with_booked_computers_conflicts_with_count(session, make_pool, make_computer):
    pool = await make_pool("Main")
    await make_computer("A1", pool, status="booked")
    await make_computer("A2", pool, status="booked")
    free = await make_computer("A3", pool)
    with pytest.raises(Conflict, match="2 забронированных"):
        await pools.delete_pool(session, pool.id)
    # ничего не изменилось
    assert await session.get(Pool, pool.id) is not None
    assert (await reload_computers(session))["A3"].pool_id == pool.id and free.pool_id == pool.id


@pytest.mark.parametrize("flag", [True, False])
async def test_delete_pool_detaches_computers_and_removes_links(session, make_pool, make_computer, make_department,
                                                                monkeypatch, flag):
    set_writeback(monkeypatch, flag)
    d1, d2 = await make_department("QA"), await make_department("Dev")
    pool = await make_pool("Main", departments=[d1, d2])
    other = await make_pool("Other", departments=[d1])
    await make_computer("A1", pool)
    await make_computer("A2", pool, status="in_use")
    await make_computer("A3", pool, is_archived=True)  # архивные тоже отвязываются
    await make_computer("A4", other)
    pid = pool.id

    await pools.delete_pool(session, pid)

    session.expire_all()
    assert await session.get(Pool, pid) is None
    comps = await reload_computers(session)
    for n in ("A1", "A2", "A3"):
        assert comps[n].pool_id is None and comps[n].writeback_pending is flag
    assert comps["A4"].pool_id == other.id and not comps["A4"].writeback_pending
    links = (await session.execute(select(pool_departments.c.pool_id, pool_departments.c.department_id))).all()
    assert links == [(other.id, d1.id)]  # связи удалённого пула сняты, чужая осталась
    assert await count(session, Department) == 2


async def test_delete_empty_pool(session, make_pool):
    pool = await make_pool("Main")
    await pools.delete_pool(session, pool.id)
    assert await count(session, Pool) == 0


async def test_delete_pool_allows_returned_booking_history(session, make_pool, make_computer, make_department, make_user):
    """Вернувшийся ПК снова available — пул удалить можно."""
    pool, dept, user = await make_pool("Main"), await make_department("QA"), await make_user("u1")
    comp = await make_computer("A1", pool)
    await add_booking(session, comp, user, dept, status="returned")
    await pools.delete_pool(session, pool.id)
    assert await count(session, Pool) == 0


# ---------- pool_stats ----------

async def test_pool_stats_counts_per_pool(session, make_pool, make_computer):
    b, a, empty = await make_pool("B"), await make_pool("A"), await make_pool("Empty")
    await make_computer("A1", a)
    await make_computer("A2", a)
    await make_computer("A3", a, status="booked")
    await make_computer("A4", a, status="in_use")           # в total, но ни свободен, ни занят порталом
    await make_computer("A5", a, is_archived=True)          # архивные не считаются
    await make_computer("B1", b, status="booked")
    await make_computer("N1")                               # без пула — не в статистике
    stats = await pools.pool_stats(session)
    assert [s["pool"].name for s in stats] == ["A", "B", "Empty"]  # по имени
    by_name = {s["pool"].name: s for s in stats}
    assert (by_name["A"]["total"], by_name["A"]["available"], by_name["A"]["booked"]) == (4, 2, 1)
    assert (by_name["B"]["total"], by_name["B"]["available"], by_name["B"]["booked"]) == (1, 0, 1)
    assert (by_name["Empty"]["total"], by_name["Empty"]["available"], by_name["Empty"]["booked"]) == (0, 0, 0)
    assert empty.id == by_name["Empty"]["pool"].id


async def test_pool_stats_no_pools(session):
    assert await pools.pool_stats(session) == []


# ---------- visible_pool_ids ----------

@pytest.fixture
async def pool_world(make_department, make_pool):
    qa, dev = await make_department("QA"), await make_department("Dev")
    return {
        "qa": qa, "dev": dev,
        "open": await make_pool("Open"),
        "qa_only": await make_pool("QaOnly", departments=[qa]),
        "dev_only": await make_pool("DevOnly", departments=[dev]),
        "both": await make_pool("Both", departments=[qa, dev]),
        "draft_open": await make_pool("DraftOpen", is_published=False),
        "draft_qa": await make_pool("DraftQa", departments=[qa], is_published=False),
    }


async def visible_names(session, user) -> set[str]:
    ids = (await session.scalars(pools.visible_pool_ids(user))).all()
    return {p.name for p in (await session.scalars(select(Pool).where(Pool.id.in_(ids)))).all()}


async def test_visible_pools_admin_sees_all_published_regardless_of_departments(session, make_user, pool_world):
    boss = await make_user("boss", role=ADMIN)
    assert await visible_names(session, boss) == {"Open", "QaOnly", "DevOnly", "Both"}


async def test_visible_pools_employee_with_department(session, make_user, pool_world):
    emp = await make_user("emp", department=pool_world["qa"])
    assert await visible_names(session, emp) == {"Open", "QaOnly", "Both"}


async def test_visible_pools_employee_without_department_sees_open_only(session, make_user, pool_world):
    emp = await make_user("emp")
    assert await visible_names(session, emp) == {"Open"}


async def test_visible_pools_unpublished_hidden_from_everyone(session, make_user, pool_world):
    emp = await make_user("emp", department=pool_world["qa"])
    names = await visible_names(session, emp)
    assert "DraftOpen" not in names and "DraftQa" not in names


async def test_visible_pools_no_pools_at_all(session, make_user):
    assert await visible_names(session, await make_user("emp")) == set()
