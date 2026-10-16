"""Первичная инициализация (bootstrap): отделы и пул по умолчанию, первая синхронизация, демо-раздача ПК по пулу,
идемпотентность и гонка двух стартующих процессов."""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models import Computer, Department, Pool
from app.services import bootstrap as bootstrap_mod
from app.services.bootstrap import DEFAULT_POOL, bootstrap


@pytest.fixture
def sync_calls(monkeypatch):
    """Подменяет run_sync: считает вызовы и (опционально) создаёт ПК, как это сделала бы синхронизация."""
    calls = {"n": 0, "create": 0}

    async def fake_sync(session):
        calls["n"] += 1
        for i in range(calls["create"]):
            session.add(Computer(name=f"S{i}", insight_object_id=i + 1))
        await session.commit()
    monkeypatch.setattr(bootstrap_mod, "run_sync", fake_sync)
    return calls


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# ---------- Справочники ----------

async def test_empty_db_creates_default_departments_and_pool(session, sync_calls):
    await bootstrap(session)
    names = set((await session.scalars(select(Department.name))).all())
    assert names == set(settings.default_department_list) and len(names) == 6
    pool = await session.scalar(select(Pool))
    assert pool.name == DEFAULT_POOL and pool.is_published is True


async def test_custom_default_departments(session, sync_calls, monkeypatch):
    monkeypatch.setattr(settings, "default_departments", "Ops, Dev")
    await bootstrap(session)
    assert set((await session.scalars(select(Department.name))).all()) == {"Ops", "Dev"}


async def test_existing_departments_are_not_touched(session, sync_calls, make_department):
    await make_department("Своё")
    await bootstrap(session)
    assert (await session.scalars(select(Department.name))).all() == ["Своё"]  # дефолтные не добавлены


async def test_existing_pool_suppresses_default_pool(session, sync_calls, make_pool):
    await make_pool("Мой пул", is_published=False)
    await bootstrap(session)
    assert (await session.scalars(select(Pool.name))).all() == ["Мой пул"]


async def test_bootstrap_is_idempotent(session, sync_calls):
    await bootstrap(session)
    await bootstrap(session)
    assert await _count(session, Department) == 6 and await _count(session, Pool) == 1


# ---------- Первая синхронизация ----------

async def test_sync_runs_only_when_no_computers(session, sync_calls, make_computer):
    await bootstrap(session)
    assert sync_calls["n"] == 1  # база пустая -> первая синхронизация
    await make_computer("A001")
    await bootstrap(session)
    assert sync_calls["n"] == 1  # ПК уже есть -> синхронизации нет


async def test_mock_mode_opens_all_computers_in_default_pool(session, sync_calls, monkeypatch):
    monkeypatch.setattr(settings, "insight_mode", "mock")
    sync_calls["create"] = 3
    await bootstrap(session)
    pool_id = await session.scalar(select(Pool.id).where(Pool.name == DEFAULT_POOL))
    assert (await session.scalars(select(Computer.pool_id))).all() == [pool_id] * 3


async def test_mock_mode_keeps_existing_pool_assignment(session, sync_calls, monkeypatch, make_pool, make_computer):
    monkeypatch.setattr(settings, "insight_mode", "mock")
    mine = await make_pool("Мой")
    await make_computer("A001", pool=mine)
    await make_computer("A002")  # без пула
    await bootstrap(session)
    # хоть один ПК уже в пуле -> админ уже всё раздал, демо-раздачу не делаем
    assert await session.scalar(select(Computer.pool_id).where(Computer.name == "A002")) is None


async def test_live_mode_leaves_computers_without_pool(session, sync_calls, monkeypatch):
    monkeypatch.setattr(settings, "insight_mode", "live")
    sync_calls["create"] = 2
    await bootstrap(session)
    assert (await session.scalars(select(Computer.pool_id))).all() == [None, None]


async def test_real_mock_sync_populates_catalog(session):
    """Без подмен: mock-Insight из репозитория -> ПК загружены и лежат в «Общем пуле»."""
    await bootstrap(session)
    computers = (await session.scalars(select(Computer))).all()
    pool_id = await session.scalar(select(Pool.id))
    assert computers and all(c.pool_id == pool_id for c in computers)


# ---------- Гонка стартующих процессов ----------

async def test_integrity_error_on_commit_is_swallowed(session, sync_calls, monkeypatch):
    """Параллельный процесс успел первым (уникальный индекс) -> rollback, старт продолжается."""
    real_commit = session.commit
    state = {"raised": False}

    async def commit():
        if not state["raised"]:
            state["raised"] = True
            raise IntegrityError("insert", {}, Exception("duplicate key"))
        await real_commit()
    monkeypatch.setattr(session, "commit", commit)
    await bootstrap(session)  # не бросает
    assert state["raised"] and sync_calls["n"] == 1
    assert await _count(session, Department) == 0  # откат: наше частичное наполнение не сохранилось


# ---------- main.lifespan ----------

@pytest.fixture
def lifespan_calls(monkeypatch):
    """Подменяет bootstrap в app.main; запоминает, что ему передали."""
    import app.main as main
    calls = []

    async def fake(session):
        calls.append(session)
    monkeypatch.setattr(main, "bootstrap", fake)
    return calls


async def test_lifespan_warns_when_bouncer_disabled(lifespan_calls, caplog):
    from app.main import app
    assert not settings.bouncer_enabled
    with caplog.at_level("INFO", logger="hmsrent"):
        async with app.router.lifespan_context(app):
            pass
    assert len(lifespan_calls) == 1  # bootstrap вызван при старте
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and "Bouncer выключен" in warnings[0].getMessage()
    assert any("запущен: bouncer=False" in r.getMessage() for r in caplog.records)


async def test_lifespan_no_warning_when_bouncer_enabled(lifespan_calls, caplog, monkeypatch):
    from app.main import app
    for k, v in dict(bouncer_client_id="cid", bouncer_client_secret="sec", bouncer_authorize_url="https://sso/a").items():
        monkeypatch.setattr(settings, k, v)
    with caplog.at_level("INFO", logger="hmsrent"):
        async with app.router.lifespan_context(app):
            pass
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("bouncer=True" in r.getMessage() for r in caplog.records)


async def test_lifespan_runs_real_bootstrap_on_clean_install(session):
    from app.main import app
    async with app.router.lifespan_context(app):
        pass
    assert await _count(session, Department) == 6 and await _count(session, Pool) == 1
    assert await _count(session, Computer) > 0
