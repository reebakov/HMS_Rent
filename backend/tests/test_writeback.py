"""Обратная запись в Insight (services/writeback.py): фейковый клиент вместо сети."""
from datetime import date

import pytest

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Computer, EventType
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


async def test_change_during_write_keeps_flag_for_next_round(session, fake, wb_on, make_computer):
    """Новая бронь пришла, пока состояние уходило в Insight: флаг не снимается, следующий круг отправит свежее."""
    comp = await pending(make_computer)

    async def booking_arrives():
        async with SessionLocal() as other:  # отдельная транзакция портала, как запрос бронирования
            row = await other.get(Computer, comp.id)
            row.status, row.writeback_pending = "booked", True
            await other.commit()

    fake.on_write = booking_arrives
    await push_pending(session)
    assert (await reload_computers(session))["A001"].writeback_pending is True

    fake.on_write = None
    await push_pending(session)  # повторный круг без вмешательства снимает флаг
    assert (await reload_computers(session))["A001"].writeback_pending is False


async def test_computers_are_sent_in_id_order_even_after_updates(session, fake, wb_on, make_computer):
    """Без ORDER BY строка после UPDATE уходит в конец выборки: пакет и ошибки раздавались бы в случайном порядке."""
    first = await pending(make_computer, "A001", 1)
    await pending(make_computer, "A002", 2)
    first.pool_id = None
    first.hostname = "pc-1"  # UPDATE строки: версия строки переезжает в конец таблицы
    await session.commit()
    await push_pending(session)
    assert [c["id"] for c in fake.calls] == [1, 2]


async def test_faulty_pc_is_written_as_maintenance(session, fake, wb_on, make_computer):
    """ПК, отмеченный неисправным исполнителем, уходит в Insight статусом обслуживания, а не «свободен»."""
    await pending(make_computer, status="maintenance")
    await push_pending(session)
    assert fake.calls[0]["values"]["Статус"] == "В ремонте"  # в демо-маппинге; в боевом — «ТО»


async def test_cleaning_pc_is_not_written_and_flag_is_cleared(session, fake, wb_on, make_computer):
    """На очистке в Insight остаётся прежнее состояние; запись идёт после подтверждения исполнителя."""
    await pending(make_computer, status="cleaning")
    assert await push_pending(session) == 0
    assert fake.calls == []
    assert (await reload_computers(session))["A001"].writeback_pending is False


# ---------- «Резерв»: свободный ПК в пуле не из общего ----------

@pytest.mark.parametrize("general, pool, status, expected", [
    ("Общий пул", "ECO Builder Studio", "available", "Резерв"),  # ушёл из общего пула — резерв
    ("Общий пул", "Общий пул", "available", "Свободен"),
    ("общий ПУЛ", "Общий пул", "available", "Свободен"),  # регистр не важен
    ("", "ECO Builder Studio", "available", "Свободен"),  # общий пул не задан — правило выключено
    ("Общий пул", None, "available", "Свободен"),
    ("Общий пул", "ECO Builder Studio", "maintenance", "В ремонте"),  # неисправность важнее резерва
])
async def test_free_pc_outside_general_pool_is_written_as_reserve(
        session, fake, wb_on, make_computer, make_pool, monkeypatch, general, pool, status, expected):
    """Регрессия: «Резерв» из Insight читался как обслуживание и после смены пула затирался на «ТО»."""
    monkeypatch.setattr(settings, "insight_default_pool", general)
    await pending(make_computer, pool=await make_pool(pool) if pool else None, status=status)
    await push_pending(session)
    assert fake.calls[0]["values"]["Статус"] == expected


async def test_booked_pc_outside_general_pool_is_written_as_in_use(session, fake, wb_on, make_computer, make_pool, make_user,
                                                                   make_department, monkeypatch):
    monkeypatch.setattr(settings, "insight_default_pool", "Общий пул")
    comp = await pending(make_computer, pool=await make_pool("ECO Builder Studio"), status="booked")
    await add_booking(session, comp, await make_user("ivanov"), await make_department("QA"), expected_return_at=date(2030, 5, 17))
    await push_pending(session)
    assert fake.calls[0]["values"]["Статус"] == "В использовании"


# ---------- чужое состояние портал не затирает ----------

@pytest.mark.parametrize("status, insight", [("in_use", "Используется"), ("retired", "Списано"), ("unknown", "Неизвестно")])
async def test_foreign_state_keeps_status_and_rental_fields_and_writes_only_pool(
        session, fake, wb_on, make_computer, make_pool, status, insight):
    """Регрессия: ПК, занятый мимо портала, при смене пула получал в Insight «Ожидает» и терял команду и срок."""
    await pending(make_computer, pool=await make_pool("ECO Builder Studio"), status=status, insight_status=insight)
    await push_pending(session)
    assert fake.calls[0]["values"] == {"Пул выдачи": "ECO Builder Studio"}


@pytest.mark.parametrize("insight, expected", [
    ("Свободен", None),  # уже свободен — статус не трогаем
    ("В использовании", "Свободен"),  # вернули — освобождаем
])
async def test_status_is_written_only_when_insight_holds_a_different_one(session, fake, wb_on, make_computer, insight, expected):
    await pending(make_computer, status="available", insight_status=insight)
    await push_pending(session)
    assert fake.calls[0]["values"].get("Статус") == expected


async def test_maintenance_in_insight_is_not_overwritten_by_tech_status(session, fake, wb_on, make_computer):
    """Регрессия: «Резерв» (и «Тест») затирались на «ТО» при любой записи по ПК; в демо-маппинге «Резерв» — обслуживание."""
    await pending(make_computer, status="maintenance", insight_status="Резерв")
    await push_pending(session)
    assert "Статус" not in fake.calls[0]["values"]


async def test_written_status_is_remembered_until_next_sync(session, fake, wb_on, make_computer):
    await pending(make_computer, status="available", insight_status="В использовании")
    await push_pending(session)
    assert (await reload_computers(session))["A001"].insight_status == "Свободен"
