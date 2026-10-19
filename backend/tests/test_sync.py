"""Синхронизация Insight -> БД (services/sync.py) и определение категории (services/tiering.py)."""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AssetEvent, Computer, EventType, Pool, SyncRun
from app.services.sync import SYNC_LOCK_KEY, run_sync
from app.services.tiering import classify
from tests.sync_fakes import FakeInsight, add_booking, events_of, insight_obj, patch_source, reload_computers

RAM, GPU = "ОЗУ", "Видеокарта"


def use(monkeypatch, *objects, **kw) -> FakeInsight:
    return patch_source(monkeypatch, FakeInsight(list(objects), **kw), "sync")


async def count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# ---------- mock-режим и идемпотентность ----------

async def test_mock_mode_imports_seed(session):
    seed = json.loads(settings.path(settings.mock_data_file).read_text(encoding="utf-8"))
    run = await run_sync(session)
    assert run.status == "success" and run.mode == "mock"
    assert (run.total, run.created, run.updated, run.archived) == (len(seed), len(seed), 0, 0)
    comps = await reload_computers(session)
    assert len(comps) == len(seed)
    assert {c.insight_object_id for c in comps.values()} == {o["id"] for o in seed}
    # первый импорт не засоряет журнал событиями «ПК появился»
    assert await count(session, AssetEvent) == 0
    # маппинг: виртуалки, статусы и категории
    assert sum(c.is_virtual for c in comps.values()) == 10
    assert all(c.tier == "vm" for c in comps.values() if c.is_virtual)
    statuses = [c.status for c in comps.values()]
    assert statuses.count("available") == 43 and statuses.count("in_use") == 8
    assert statuses.count("maintenance") == 8 and statuses.count("retired") == 1


async def test_resync_is_idempotent(session):
    first = await run_sync(session)
    second = await run_sync(session)
    assert second.status == "success"
    assert (second.created, second.updated, second.archived) == (0, 0, 0)
    assert await count(session, Computer) == first.total
    assert await count(session, AssetEvent) == 0
    # insight_object_id уникален: второй дубль на уровне БД невозможен
    ids = (await session.scalars(select(Computer.insight_object_id))).all()
    assert len(ids) == len(set(ids))


async def test_insight_object_id_unique_in_db(session, make_computer):
    from sqlalchemy.exc import IntegrityError
    await make_computer("X1", insight_object_id=77)
    with pytest.raises(IntegrityError):
        await make_computer("X2", insight_object_id=77)


async def test_new_object_after_first_import_creates_event(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001"))
    await run_sync(session)
    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    run = await run_sync(session)
    assert run.created == 1
    comps = await reload_computers(session)
    assert [e.event_type for e in await events_of(session, comps["A002"])] == [EventType.insight_created]
    assert await events_of(session, comps["A001"]) == []


async def test_changed_attributes_counted_as_update(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001", **{RAM: "8 GB"}))
    await run_sync(session)
    use(monkeypatch, insight_obj(1, "A001", **{RAM: "16 GB"}))
    run = await run_sync(session)
    assert run.updated == 1
    c = (await reload_computers(session))["A001"]
    assert c.ram_gb == 16 and c.tier == "medium"


# ---------- архивирование ----------

async def test_missing_object_archived_and_restored(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    await run_sync(session)

    use(monkeypatch, insight_obj(1, "A001"))
    run = await run_sync(session)
    comps = await reload_computers(session)
    assert run.archived == 1 and comps["A002"].is_archived and not comps["A001"].is_archived
    assert [e.event_type for e in await events_of(session, comps["A002"])] == [EventType.insight_removed]

    run = await run_sync(session)  # повторно — архивирован уже, второго события нет
    assert run.archived == 0
    assert len(await events_of(session, comps["A002"], EventType.insight_removed)) == 1

    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    await run_sync(session)
    comp = (await reload_computers(session))["A002"]
    assert comp.is_archived is False and await count(session, Computer) == 2  # не дубль, а тот же ПК


async def test_trial_run_with_limit_does_not_archive(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    await run_sync(session)
    monkeypatch.setattr(settings, "insight_max_objects", 1)
    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    run = await run_sync(session)
    assert run.archived == 0 and "Пробная" in (run.error or "")
    assert not any(c.is_archived for c in (await reload_computers(session)).values())


# ---------- события статуса ----------

async def test_insight_status_change_creates_event(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001", status="Свободен"))
    await run_sync(session)
    use(monkeypatch, insight_obj(1, "A001", status="В ремонте"))
    await run_sync(session)
    c = (await reload_computers(session))["A001"]
    assert c.status == "maintenance" and c.insight_status == "В ремонте"
    (ev,) = await events_of(session, c, EventType.insight_status_changed)
    assert (ev.from_status, ev.to_status) == ("Свободен", "В ремонте")
    await run_sync(session)  # без изменений — нового события нет
    assert len(await events_of(session, c, EventType.insight_status_changed)) == 1


async def test_unknown_insight_status_maps_to_default(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001", status="Что-то новое"))
    await run_sync(session)
    assert (await reload_computers(session))["A001"].status == "unknown"


# ---------- портал главнее Insight ----------

async def test_booked_computer_keeps_booked_status(session, monkeypatch, make_computer, make_user, make_department):
    dept, user = await make_department("QA"), await make_user("ivanov")
    comp = await make_computer("A001", status="booked", insight_object_id=1, insight_status="В использовании",
                               department_id=dept.id, order_number=5, usage_until=date(2030, 1, 1))
    await add_booking(session, comp, user, dept)
    # в Insight ПК «свободен», без команды и срока — портал не должен это принять
    use(monkeypatch, insight_obj(1, "A001", status="Свободен"))
    await run_sync(session)
    c = (await reload_computers(session))["A001"]
    assert c.status == "booked" and c.insight_status == "Свободен"
    assert c.department_id == dept.id and c.order_number == 5 and c.usage_until == date(2030, 1, 1)


async def test_writeback_pending_ignores_foreign_status(session, monkeypatch, make_computer, make_pool):
    old_pool = await make_pool("Old")
    await make_computer("A001", status="available", insight_object_id=1, writeback_pending=True,
                         pool=old_pool, order_number=None)
    use(monkeypatch, insight_obj(1, "A001", status="В ремонте", **{"Пул выдачи": "Other", "Номер заказа": "9"}))
    await run_sync(session)
    c = (await reload_computers(session))["A001"]
    assert c.status == "available"  # наш ещё не отправленный статус не затирается
    assert c.insight_status == "В ремонте"  # а «сырой» статус Insight обновляется
    assert c.pool_id == old_pool.id and c.order_number is None  # поля аренды тоже не тянем


async def test_non_booked_pulls_rental_fields(session, monkeypatch, make_department):
    dept = await make_department("QA")
    use(monkeypatch, insight_obj(1, "A001", **{"Команда-получатель": "qa", "Срок использования": "20.10.2030",
                                               "Номер заказа": "42"}),
        insight_obj(2, "A002", **{"Команда-получатель": "Нет такого"}))
    await run_sync(session)
    comps = await reload_computers(session)
    assert (comps["A001"].department_id, comps["A001"].usage_until, comps["A001"].order_number) == (
        dept.id, date(2030, 10, 20), 42)
    assert comps["A002"].department_id is None


# ---------- пулы ----------

async def test_pool_change_in_insight(session, monkeypatch, make_pool):
    old, new = await make_pool("Old"), await make_pool("New")
    use(monkeypatch, insight_obj(1, "A001", **{"Пул выдачи": "Old"}))
    await run_sync(session)
    use(monkeypatch, insight_obj(1, "A001", **{"Пул выдачи": "new"}))  # регистр не важен
    await run_sync(session)
    c = (await reload_computers(session))["A001"]
    assert c.pool_id == new.id and old.id != new.id
    (ev,) = await events_of(session, c, EventType.insight_pool_changed)
    assert "Old" in ev.message and "New" in ev.message


async def test_unknown_pool_created_unpublished(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001", **{"Пул выдачи": "Brand new"}))
    await run_sync(session)
    pool = await session.scalar(select(Pool).where(Pool.name == "Brand new"))
    assert pool is not None and pool.is_published is False
    assert (await reload_computers(session))["A001"].pool_id == pool.id


async def test_empty_pool_in_insight_does_not_reset(session, monkeypatch, make_pool):
    pool = await make_pool("Keep")
    use(monkeypatch, insight_obj(1, "A001", **{"Пул выдачи": "Keep"}))
    await run_sync(session)
    use(monkeypatch, insight_obj(1, "A001"))
    await run_sync(session)
    assert (await reload_computers(session))["A001"].pool_id == pool.id


# ---------- SyncRun и ошибки источника ----------

async def test_failing_source_keeps_data_and_logs_run(session, monkeypatch):
    fake = use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    await run_sync(session)
    before = {n: (c.status, c.is_archived, c.synced_at) for n, c in (await reload_computers(session)).items()}

    fake.fetch_error = RuntimeError("Insight упал: 502")
    run = await run_sync(session)
    assert run.status == "failed" and "502" in run.error and run.mode == "mock"
    after = {n: (c.status, c.is_archived, c.synced_at) for n, c in (await reload_computers(session)).items()}
    assert after == before
    assert fake.closed
    runs = (await session.scalars(select(SyncRun).order_by(SyncRun.id))).all()
    assert [r.status for r in runs] == ["success", "failed"]


async def test_source_creation_error_is_logged(session, monkeypatch):
    def boom():
        raise ValueError("не задан JIRA_URL")
    monkeypatch.setattr("app.services.sync.create_insight_source", boom)
    run = await run_sync(session)
    assert run.status == "failed" and "JIRA_URL" in run.error


async def test_empty_response_does_not_archive_everything(session, monkeypatch):
    fake = use(monkeypatch, insight_obj(1, "A001"))
    await run_sync(session)
    fake.objects = []
    run = await run_sync(session)
    assert run.status == "failed" and "0 объектов" in run.error
    assert (await reload_computers(session))["A001"].is_archived is False


async def test_empty_source_on_empty_db_is_success(session, monkeypatch):
    use(monkeypatch)
    run = await run_sync(session)
    assert run.status == "success" and run.total == 0


async def test_success_run_counters(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    run = await run_sync(session)
    assert (run.total, run.created, run.updated, run.archived) == (2, 2, 0, 0)
    assert run.finished_at is not None and run.error is None


async def test_concurrent_sync_is_skipped(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "A001"))
    async with SessionLocal() as other:  # «другой воркер» держит advisory-lock
        await other.execute(select(func.pg_advisory_xact_lock(SYNC_LOCK_KEY)))
        assert await run_sync(session) is None
        await other.rollback()
    assert await count(session, Computer) == 0


# ---------- категории ----------

@pytest.mark.parametrize("ram,expected", [
    (None, "weak"), (4, "weak"), (8, "weak"), (14, "weak"),
    (15, "medium"), (16, "medium"), (31, "medium"),
    (32, "powerful"), (64, "powerful"),
])
def test_classify_ram_boundaries(ram, expected):
    assert classify(is_virtual=False, ram_gb=ram, gpu=None) == expected


@pytest.mark.parametrize("gpu,expected", [
    ("Intel UHD Graphics 630", "weak"),
    ("NVIDIA GTX 1050 Ti", "medium"), ("GTX 1650", "medium"), ("Radeon RX 580", "medium"),
    ("NVIDIA RTX 3060", "powerful"), ("rtx 4090", "powerful"), ("GTX 1660 Super", "powerful"),
    ("Radeon RX 6600", "powerful"), ("RTX A4000", "powerful"),
    (None, "weak"), ("", "weak"),
])
def test_classify_gpu_patterns(gpu, expected):
    assert classify(is_virtual=False, ram_gb=8, gpu=gpu) == expected


def test_classify_gpu_beats_ram_and_virtual_beats_all():
    assert classify(is_virtual=False, ram_gb=8, gpu="RTX 3070") == "powerful"
    assert classify(is_virtual=False, ram_gb=64, gpu="GTX 1050") == "powerful"  # больший класс побеждает
    assert classify(is_virtual=True, ram_gb=64, gpu="RTX 3070") == "vm"


@pytest.mark.parametrize("ram_attr,expected", [("8 GB", "weak"), ("15GB", "medium"), ("16384 MB", "medium"),
                                               ("32", "powerful")])
async def test_sync_assigns_tier_from_ram(session, monkeypatch, ram_attr, expected):
    use(monkeypatch, insight_obj(1, "A001", **{RAM: ram_attr}))
    await run_sync(session)
    assert (await reload_computers(session))["A001"].tier == expected


async def test_sync_virtual_object_is_vm_tier(session, monkeypatch):
    use(monkeypatch, insight_obj(1, "V001", otype="Виртуальная машина", **{RAM: "64 GB"}))
    await run_sync(session)
    c = (await reload_computers(session))["V001"]
    assert c.is_virtual and c.tier == "vm"


async def test_tier_override_wins_and_survives_resync(session, monkeypatch, make_computer):
    await make_computer("A001", insight_object_id=1, tier="powerful", tier_override="powerful")
    use(monkeypatch, insight_obj(1, "A001", **{RAM: "4 GB"}))
    await run_sync(session)
    await run_sync(session)
    assert (await reload_computers(session))["A001"].tier == "powerful"
