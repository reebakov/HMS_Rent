"""Обратная запись в Insight (services/writeback.py): фейковый клиент вместо сети."""
from datetime import date

import pytest

from app.models import EventType
from app.services import runtime
from app.services.writeback import push_pending
from tests.sync_fakes import FakeInsight, add_booking, events_of, patch_source, reload_computers

EXTRAS = {"Пул выдачи", "Команда-получатель", "Пользователь", "Срок использования", "Номер заказа"}


@pytest.fixture
def fake(monkeypatch):
    return patch_source(monkeypatch, FakeInsight(), "writeback")


@pytest.fixture
async def wb_on(session):
    await runtime.update(session, {"insight_writeback": True})


async def pending(make_computer, name="A001", oid=1, **kw):
    return await make_computer(name, insight_object_id=oid, insight_object_type_id=21, writeback_pending=True, **kw)


async def test_disabled_sends_nothing(session, fake, make_computer):
    comp = await pending(make_computer)
    assert await push_pending(session) == 0
    assert fake.calls == []
    assert (await reload_computers(session))["A001"].writeback_pending is True and comp.writeback_error is None


async def test_enabled_via_runtime_cache(session, fake, make_computer):
    """Флаг можно включить и подменой кэша runtime (без записи в БД)."""
    runtime._cache = (float("inf"), runtime.RuntimeConfig(insight_writeback=True))
    await pending(make_computer)
    assert await push_pending(session) == 1 and len(fake.calls) == 1


async def test_booked_sends_full_state(session, fake, wb_on, make_computer, make_pool, make_user, make_department):
    dept, user, pool = await make_department("QA"), await make_user("ivanov"), await make_pool("Main")
    comp = await pending(make_computer, pool=pool, status="booked")
    booking = await add_booking(session, comp, user, dept, expected_return_at=date(2030, 5, 17))

    assert await push_pending(session) == 1
    (call,) = fake.calls
    assert (call["id"], call["type_id"]) == (1, 21)
    assert call["values"] == {
        "Статус": "В использовании", "Пул выдачи": "Main", "Команда-получатель": "QA", "Пользователь": "ivanov",
        "Срок использования": "2030-05-17", "Номер заказа": str(booking.order_number),
    }
    assert call["optional"] == EXTRAS  # всё, кроме статуса, — необязательные поля
    c = (await reload_computers(session))["A001"]
    assert c.writeback_pending is False and c.writeback_error is None
    assert fake.closed


async def test_free_computer_clears_rental_fields(session, fake, wb_on, make_computer):
    await pending(make_computer)  # без брони и без пула
    await push_pending(session)
    assert fake.calls[0]["values"] == {
        "Статус": "Свободен", "Пул выдачи": None, "Команда-получатель": None, "Пользователь": None,
        "Срок использования": None, "Номер заказа": None,
    }


async def test_booking_without_return_date(session, fake, wb_on, make_computer, make_user, make_department):
    comp = await pending(make_computer, status="booked")
    await add_booking(session, comp, await make_user("u"), await make_department("QA"))
    await push_pending(session)
    assert fake.calls[0]["values"]["Срок использования"] is None


async def test_returned_booking_means_free(session, fake, wb_on, make_computer, make_user, make_department):
    comp = await pending(make_computer)
    await add_booking(session, comp, await make_user("u"), await make_department("QA"), status="returned")
    await push_pending(session)
    assert fake.calls[0]["values"]["Статус"] == "Свободен"


async def test_only_pending_computers_are_sent(session, fake, wb_on, make_computer):
    await pending(make_computer, "A001", 1)
    await make_computer("A002", insight_object_id=2, insight_object_type_id=21)  # флага нет
    assert await push_pending(session) == 1
    assert [c["id"] for c in fake.calls] == [1]


async def test_batch_limit(session, fake, wb_on, make_computer):
    for i in range(1, 4):
        await pending(make_computer, f"A00{i}", i)
    assert await push_pending(session, batch=2) == 2
    left = [c for c in (await reload_computers(session)).values() if c.writeback_pending]
    assert len(left) == 1


async def test_computer_without_insight_id_is_just_cleared(session, fake, wb_on, make_computer):
    await make_computer("Local", writeback_pending=True)
    assert await push_pending(session) == 1
    assert fake.calls == []
    assert (await reload_computers(session))["Local"].writeback_pending is False


async def test_no_pending_does_not_open_source(session, fake, wb_on, make_computer):
    await make_computer("A001", insight_object_id=1)
    assert await push_pending(session) == 0
    assert fake.closed is False


async def test_failure_keeps_flag_and_logs_event_once(session, fake, wb_on, make_computer):
    # при сбое запись повторяется «только статус» (см. _write) — поэтому на каждый цикл по две ошибки
    fake.write_errors = [RuntimeError("Insight 500")] * 4 + [None]
    await pending(make_computer)

    assert await push_pending(session) == 0
    c = (await reload_computers(session))["A001"]
    assert c.writeback_pending is True and c.writeback_error == "Insight 500"
    (ev,) = await events_of(session, c, EventType.writeback_failed)
    assert "Insight 500" in ev.message

    await push_pending(session)  # та же ошибка — журнал не спамим
    assert len(await events_of(session, c, EventType.writeback_failed)) == 1
    assert (await reload_computers(session))["A001"].writeback_pending is True

    assert await push_pending(session) == 1  # Insight ожил: флаг снят, ошибка сброшена
    c = (await reload_computers(session))["A001"]
    assert c.writeback_pending is False and c.writeback_error is None


async def test_failure_of_one_does_not_block_others(session, fake, wb_on, make_computer):
    fake.write_errors = [RuntimeError("boom")] * 2 + [None]  # у первого падают и запись, и повтор со статусом
    await pending(make_computer, "A001", 1)
    await pending(make_computer, "A002", 2)
    assert await push_pending(session) == 1
    comps = await reload_computers(session)
    assert comps["A001"].writeback_pending is True and comps["A002"].writeback_pending is False


async def test_extras_failure_still_writes_status(session, fake, wb_on, make_computer):
    """Не прошли доп. поля -> повтор только со статусом, флаг снят, предупреждение осталось для админа."""
    fake.write_errors = [RuntimeError("нет атрибута «Номер заказа»"), None]
    await pending(make_computer)
    assert await push_pending(session) == 1
    assert len(fake.calls) == 2 and fake.calls[1]["values"] == {"Статус": "Свободен"}
    c = (await reload_computers(session))["A001"]
    assert c.writeback_pending is False
    assert "Статус записан" in c.writeback_error and "Номер заказа" in c.writeback_error
    assert len(await events_of(session, c, EventType.writeback_failed)) == 1
