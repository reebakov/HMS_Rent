"""Запись ВМ в её объект Insight: занята → «Используется» и поля аренды, освобождена → «На складе» и пустые поля."""
from datetime import date

import pytest

from app.integrations.insight.mapping import InsightMapping, WritebackMapping
from app.services import runtime, vm_insight
from tests.test_overdue import add_vm

ATTRS = {"team": "Команда-получатель", "usage_period": "Срок использования", "order_number": "Номер заказа",
         "ip_address": "IP Address"}


class FakeSource:
    def __init__(self):
        self.mapping = InsightMapping(
            query="q", attributes=ATTRS,
            writeback=WritebackMapping(status_attribute="Status",
                                       vm_status_values={"taken": "Используется", "free": "На складе"}),
        )
        self.updates: list[tuple[int, int | None, dict, set | None]] = []
        self.errors: list[Exception | None] = []
        self.closed = False

    async def update_object(self, object_id, object_type_id, values, optional=None):
        if self.errors and (err := self.errors.pop(0)):
            raise err
        self.updates.append((object_id, object_type_id, dict(values), optional))

    async def close(self):
        self.closed = True


@pytest.fixture
def source(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr(vm_insight, "create_insight_source", lambda: fake)
    return fake


@pytest.fixture
async def writeback_on(session):
    await runtime.update(session, {"insight_writeback": True})


@pytest.fixture
async def ctx(make_user, make_department):
    dept = await make_department("QA")
    return dept, await make_user("u", department=dept)


async def vm_with_object(session, ctx, *, status="ready", object_id=50, **kw):
    dept, user = ctx
    return await add_vm(session, user, dept, status=status, insight_object_id=object_id,
                        insight_object_type_id=7, insight_pending=True, expected_return_at=date(2026, 12, 1),
                        ip_address="10.0.0.5", **kw)


async def test_live_vm_writes_status_and_rent_fields(session, writeback_on, source, ctx):
    vm = await vm_with_object(session, ctx)
    assert await vm_insight.push_pending(session) == 1
    (object_id, type_id, values, optional), = source.updates
    assert (object_id, type_id) == (50, 7)
    assert values == {"Status": "Используется", "Команда-получатель": "QA", "Срок использования": "2026-12-01",
                      "Номер заказа": str(vm.order_number), "IP Address": "10.0.0.5"}
    assert optional == {"Команда-получатель", "Срок использования", "Номер заказа", "IP Address"}  # доп. поля необязательны
    await session.refresh(vm)
    assert vm.insight_pending is False and source.closed


@pytest.mark.parametrize("status", ["deleted", "failed"])
async def test_released_vm_frees_object_and_clears_fields(session, writeback_on, source, ctx, status):
    await vm_with_object(session, ctx, status=status)
    await vm_insight.push_pending(session)
    (_, _, values, _), = source.updates
    assert values == {"Status": "На складе", "Команда-получатель": None, "Срок использования": None,
                      "Номер заказа": None, "IP Address": None}


async def test_released_vm_does_not_touch_object_already_taken_by_new_vm(session, writeback_on, source, ctx):
    old = await vm_with_object(session, ctx, status="deleted")
    await vm_with_object(session, ctx, status="queued")  # тот же номер уже достался новому заказу
    await vm_insight.push_pending(session)
    assert [u[2]["Status"] for u in source.updates] == ["Используется"]  # «На складе» старой ВМ не записано
    await session.refresh(old)
    assert old.insight_pending is False  # и повторять эту запись незачем


async def test_nothing_written_when_writeback_disabled(session, source, ctx):
    vm = await vm_with_object(session, ctx)
    assert await vm_insight.push_pending(session) == 0
    await session.refresh(vm)
    assert source.updates == [] and vm.insight_pending is True  # запись включат — уйдёт состояние на тот момент


async def test_vm_without_insight_object_is_ignored(session, writeback_on, source, ctx):
    dept, user = ctx
    await add_vm(session, user, dept, insight_pending=True)  # прежняя ВМ rent-…: объекта в Insight нет
    assert await vm_insight.push_pending(session) == 0 and source.updates == []


async def test_error_keeps_pending_and_next_round_retries(session, writeback_on, source, ctx):
    vm = await vm_with_object(session, ctx)
    source.errors = [RuntimeError("Insight 500")] * 2  # и запись с полями, и запись одного статуса падают
    assert await vm_insight.push_pending(session) == 0
    await session.refresh(vm)
    assert vm.insight_pending is True
    assert await vm_insight.push_pending(session) == 1
    await session.refresh(vm)
    assert vm.insight_pending is False


async def test_extra_fields_failure_still_writes_status(session, writeback_on, source, ctx):
    await vm_with_object(session, ctx)
    source.errors = [RuntimeError("нет атрибута")]  # первая запись (все поля) падает
    await vm_insight.push_pending(session)
    (_, _, values, _), = source.updates
    assert values == {"Status": "Используется"}  # статус записан отдельно, как у ПК
