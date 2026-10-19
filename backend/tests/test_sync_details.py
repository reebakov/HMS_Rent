"""Детали запуска синхронизации (sync_runs.details): что создано, изменено и архивировано."""
import pytest
from sqlalchemy import select

from app.models import SyncRun
from app.services import sync
from app.services.sync import FIELD_LABELS, NOISY_ATTRIBUTES, _fmt, run_sync
from tests.sync_fakes import FakeInsight, insight_obj, patch_source, reload_computers

RAM, CPU, LOCATION, POOL = "ОЗУ", "Процессор", "Расположение", "Пул выдачи"
EMPTY = {"updated": [], "created": [], "archived": []}


def use(monkeypatch, *objects, **kw) -> FakeInsight:
    return patch_source(monkeypatch, FakeInsight(list(objects), **kw), "sync")


async def sync_with(session, monkeypatch, *objects) -> SyncRun:
    use(monkeypatch, *objects)
    return await run_sync(session)


def changes_of(run: SyncRun, name: str) -> list[dict]:
    (item,) = [u for u in run.details["updated"] if u["name"] == name]
    return item["changes"]


# ---------- _fmt ----------

@pytest.mark.parametrize("value,expected", [
    (None, "—"), ("", "—"), (True, "да"), (False, "нет"), (0, "0"), (16, "16"), ("i5-7500", "i5-7500"),
    ("x" * 200, "x" * 200), ("x" * 201, "x" * 200), ("я" * 500, "я" * 200),
])
def test_fmt(value, expected):
    assert _fmt(value) == expected


# ---------- created / archived / updated ----------

async def test_created_lists_new_computers(session, monkeypatch):
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    comps = await reload_computers(session)
    assert run.details == {"updated": [], "archived": [],
                           "created": [{"id": comps["A001"].id, "name": "A001"}, {"id": comps["A002"].id, "name": "A002"}]}
    persisted = await session.scalar(select(SyncRun).where(SyncRun.id == run.id).execution_options(populate_existing=True))
    assert persisted.details == run.details  # лежит в БД, а не только в объекте


async def test_archived_lists_missing_computers(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001"), insight_obj(2, "A002"))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001"))
    comps = await reload_computers(session)
    assert run.details["archived"] == [{"id": comps["A002"].id, "name": "A002"}]
    assert run.details["created"] == [] and run.details["updated"] == []


async def test_updated_has_changes_with_labels(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **{RAM: "8 GB"}))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **{RAM: "16 GB"}))
    comp = (await reload_computers(session))["A001"]
    assert run.details["updated"] == [{"id": comp.id, "name": "A001",
                                       "changes": [{"field": "ОЗУ, ГБ", "old": "8", "new": "16"}]}]


async def test_mixed_run_goes_to_separate_lists(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **{CPU: "i5"}), insight_obj(2, "A002"),
                    insight_obj(3, "A003"))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **{CPU: "i7"}), insight_obj(3, "A003"),
                          insight_obj(4, "A004"))
    d = run.details
    assert [x["name"] for x in d["updated"]] == ["A001"]
    assert [x["name"] for x in d["created"]] == ["A004"]
    assert [x["name"] for x in d["archived"]] == ["A002"]
    assert (run.updated, run.created, run.archived) == (1, 1, 1)  # счётчики совпадают со списками


async def test_no_changes_gives_empty_lists(session, monkeypatch):
    objs = (insight_obj(1, "A001", **{RAM: "8 GB"}), insight_obj(2, "A002"))
    await sync_with(session, monkeypatch, *objs)
    run = await sync_with(session, monkeypatch, *objs)
    assert run.details == EMPTY


# ---------- содержимое changes ----------

@pytest.mark.parametrize("before,after,field,old,new", [
    ({CPU: "i5-7500"}, {CPU: "i7-9700"}, "Процессор", "i5-7500", "i7-9700"),
    ({}, {CPU: "i5-7500"}, "Процессор", "—", "i5-7500"),  # пусто -> значение
    ({CPU: "i5-7500"}, {}, "Процессор", "i5-7500", "—"),  # значение -> пусто
    ({LOCATION: "Офис 1"}, {LOCATION: "Офис 2"}, "Расположение", "Офис 1", "Офис 2"),
    ({"Hostname": "pc-1"}, {"Hostname": "pc-2"}, "Hostname", "pc-1", "pc-2"),
    ({"Ядра": "4"}, {"Ядра": "8"}, "Ядра", "4", "8"),
])
async def test_field_change_uses_label_and_fmt(session, monkeypatch, before, after, field, old, new):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **before))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **after))
    assert changes_of(run, "A001") == [{"field": field, "old": old, "new": new}]


async def test_status_and_rename_changes(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", status="Свободен"))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A002", status="В ремонте"))
    assert changes_of(run, "A002") == [{"field": "Имя", "old": "A001", "new": "A002"},
                                       {"field": "Статус Insight", "old": "Свободен", "new": "В ремонте"}]


async def test_bool_change_shown_as_yes_no(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001"))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", otype="Виртуальная машина"))
    assert {"field": "Виртуальная", "old": "нет", "new": "да"} in changes_of(run, "A001")


async def test_long_value_truncated_in_changes(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **{LOCATION: "a" * 250}))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **{LOCATION: "b" * 250}))
    (ch,) = changes_of(run, "A001")
    assert (ch["old"], ch["new"]) == ("a" * 200, "b" * 200)


# ---------- атрибуты Insight вне полей портала ----------

async def test_extra_insight_attributes_in_changes_sorted(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **{"Инв. номер": "100", "Владелец": "Иванов"}))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **{"Инв. номер": "200", "Гарантия": "2027"}))
    assert changes_of(run, "A001") == [
        {"field": "Владелец", "old": "Иванов", "new": "—"},  # атрибут исчез
        {"field": "Гарантия", "old": "—", "new": "2027"},  # атрибут появился
        {"field": "Инв. номер", "old": "100", "new": "200"},
    ]


async def test_noisy_attributes_not_in_changes_but_still_update(session, monkeypatch):
    assert NOISY_ATTRIBUTES == {"Updated", "Created", "Key"}
    await sync_with(session, monkeypatch, insight_obj(1, "A001", Updated="1", Created="1", Key="ITAM-1", Прочее="x"))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", Updated="2", Created="2", Key="ITAM-9", Прочее="y"))
    assert changes_of(run, "A001") == [{"field": "Прочее", "old": "x", "new": "y"}]

    # изменился только «шум»: ПК считается изменённым (атрибуты обновились), но показывать в деталях нечего
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", Updated="3", Created="3", Key="ITAM-9", Прочее="y"))
    assert run.updated == 1 and changes_of(run, "A001") == []


async def test_mapped_attributes_not_duplicated_as_extra(session, monkeypatch):
    """«ОЗУ» уже показано как поле портала «ОЗУ, ГБ», а пул/команда — это поля аренды, не «прочие атрибуты»."""
    await sync_with(session, monkeypatch, insight_obj(1, "A001", **{RAM: "8 GB", POOL: "Main"}))
    run = await sync_with(session, monkeypatch, insight_obj(1, "A001", **{RAM: "16 GB", POOL: "Other"}))
    assert [c["field"] for c in changes_of(run, "A001")] == ["ОЗУ, ГБ"]


def test_field_labels_cover_only_tracked_fields():
    assert set(FIELD_LABELS) <= set(sync.TRACKED)


# ---------- DETAILS_LIMIT ----------

async def test_details_limit_caps_lists_but_not_counters(session, monkeypatch):
    monkeypatch.setattr(sync, "DETAILS_LIMIT", 2)
    names = [f"A{i:03d}" for i in range(1, 6)]
    run = await sync_with(session, monkeypatch, *[insight_obj(i, n, **{CPU: "i5"}) for i, n in enumerate(names, 1)])
    assert run.created == 5 and [c["name"] for c in run.details["created"]] == names[:2]

    run = await sync_with(session, monkeypatch, *[insight_obj(i, n, **{CPU: "i7"}) for i, n in enumerate(names, 1)])
    assert run.updated == 5 and [u["name"] for u in run.details["updated"]] == names[:2]

    run = await sync_with(session, monkeypatch, insight_obj(1, names[0], **{CPU: "i7"}))
    assert run.archived == 4 and len(run.details["archived"]) == 2


def test_details_limit_default_is_sane():
    assert sync.DETAILS_LIMIT >= 100


# ---------- ошибки ----------

async def test_failed_source_saves_error_without_details(session, monkeypatch):
    use(monkeypatch, fetch_error=RuntimeError("Insight недоступен"))
    run = await run_sync(session)
    assert run.status == "failed" and "Insight недоступен" in run.error
    persisted = await session.scalar(select(SyncRun).where(SyncRun.id == run.id).execution_options(populate_existing=True))
    assert persisted.details == {}


async def test_empty_source_after_import_fails_and_changes_nothing(session, monkeypatch):
    await sync_with(session, monkeypatch, insight_obj(1, "A001"))
    run = await sync_with(session, monkeypatch)  # Insight вернул 0 объектов — это ошибка запроса, а не «всё ушло»
    assert run.status == "failed" and "0 объектов" in run.error
    assert not (await reload_computers(session))["A001"].is_archived
