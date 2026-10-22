"""Реакция портала на задачи, закрытые в Jira (services/jira_closure.py), и закрытие возвратов порталом.

Клиент Jira подменён FakeSd из test_service_requests: подробности закрытия (резолюция, кто закрыл) и комментарии
задаются в тесте.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import (
    AssetEvent,
    Booking,
    BookingStatus,
    Computer,
    ComputerStatus,
    EventType,
    Notification,
    NotificationKind,
    ServiceRequest,
)
from app.services import jira_closure, service_requests

from .test_executor import env  # noqa: F401 — фикстура: заказчик, исполнитель, две активные брони и одна возвращённая
from .test_service_requests import boom, sd  # noqa: F401 — sd: Service Desk подключён, клиент Jira подменён


@pytest.fixture(autouse=True)
def fake(sd, monkeypatch):  # noqa: F811
    """Реакция на закрытие и чтение комментариев ходят к той же подмене Jira."""
    monkeypatch.setattr(jira_closure, "sd", service_requests.sd)
    sd.status = real_sd.SdStatus("Done", "done")
    sd.comments = [real_sd.SdComment("Олег", "Диск заменили, всё готово", None, False)]
    return sd


async def _task(session, env, booking, kind="prepare", **kw) -> ServiceRequest:  # noqa: F811
    kw.setdefault("status", "Done")
    kw.setdefault("status_category", "done")
    req = ServiceRequest(kind=kind, user_id=env.owner.id, booking_id=booking.id, summary="s", description="d",
                         issue_key="DR-7", **kw)
    session.add(req)
    await session.commit()
    return req


async def _fresh(model, obj_id):
    async with SessionLocal() as s:
        return await s.get(model, obj_id)


async def _notes() -> list[Notification]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(Notification).order_by(Notification.id))).all())


# ---------- «подготовить ПК» закрыта в Jira ----------

async def test_rejected_in_jira_cancels_order_by_the_closer(session, env, sd):  # noqa: F811
    req = await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected", closed_by=("worker", ""))
    await jira_closure.apply_closures(session)

    booking = await _fresh(Booking, env.early.id)
    assert booking.status == BookingStatus.cancelled
    assert booking.return_comment == "Закрыто в Jira: Диск заменили, всё готово"
    assert booking.returned_by_id is None  # заказчик не видит исполнителя
    (event,) = [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.rejected]
    assert event.actor_id == env.worker.id  # закрыл тот, кто есть в портале
    assert (await _fresh(Computer, env.early.computer_id)).status == ComputerStatus.available
    (note,) = await _notes()
    assert (note.kind, note.user_id) == (NotificationKind.order_rejected, env.owner.id)
    assert "Закрыто в Jira" in note.title
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None


@pytest.mark.parametrize("closed_by", [None, ("stranger", "stranger@corp.test"), ("", "")])
async def test_rejected_by_unknown_closer_has_no_actor(session, env, sd, closed_by):  # noqa: F811
    await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected", closed_by=closed_by)
    sd.comments = []
    await jira_closure.apply_closures(session)
    assert (await _fresh(Booking, env.early.id)).return_comment == "Закрыто в Jira: Задача закрыта в Jira без комментария"
    (event,) = [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.rejected]
    assert event.actor_id is None


@pytest.mark.parametrize("closed_by", [("", "WORKER@corp.test"), ("WORKER", "")], ids=["по почте", "по логину"])
async def test_closer_is_found_by_login_or_email_ignoring_case(session, env, sd, closed_by, make_user):  # noqa: F811
    env.worker.email = "worker@corp.test"
    await session.commit()
    await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected", closed_by=closed_by)
    await jira_closure.apply_closures(session)
    (event,) = [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.rejected]
    assert event.actor_id == env.worker.id


async def test_done_without_connection_data_keeps_order_and_asks_customer(session, env, sd):  # noqa: F811
    req = await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=True, resolution="Done", closed_by=("worker", ""))
    await jira_closure.apply_closures(session)

    booking = await _fresh(Booking, env.early.id)
    assert booking.status == BookingStatus.active and booking.prepared_at is None  # заказ ждёт данных
    (note,) = await _notes()
    assert (note.kind, note.user_id) == (NotificationKind.request_status, env.owner.id)
    assert "Исполнитель завершил работу по заказу" in note.title
    assert note.body.startswith("Уточните дополнительно, если нужны данные подключения.")
    assert "Комментарий исполнителя: Диск заменили, всё готово" in note.body
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None

    await jira_closure.apply_closures(session)  # второй круг ничего не повторяет
    assert len(await _notes()) == 1


async def test_done_without_resolution_is_treated_as_done_not_rejected(session, env, sd):  # noqa: F811
    await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=False, resolution=None)  # права на резолюцию нет: ничего не отменяем
    await jira_closure.apply_closures(session)
    assert (await _fresh(Booking, env.early.id)).status == BookingStatus.active


async def test_done_without_comment_asks_customer_without_comment(session, env, sd):  # noqa: F811
    await _task(session, env, env.early)
    sd.comments = [real_sd.SdComment("Иван", "[HMS Rent] Иван: когда?", None, True)]  # свой комментарий с портала не берём
    await jira_closure.apply_closures(session)
    (note,) = await _notes()
    assert note.body == "Уточните дополнительно, если нужны данные подключения."


async def test_prepared_order_closed_in_jira_needs_nothing(session, env, sd):  # noqa: F811
    env.early.prepared_at = datetime.now(timezone.utc)
    req = await _task(session, env, env.early)
    await jira_closure.apply_closures(session)
    assert await _notes() == [] and (await _fresh(ServiceRequest, req.id)).handled_at is not None


async def test_already_closed_order_is_left_alone(session, env, sd):  # noqa: F811
    req = await _task(session, env, env.closed)  # заказ закрыт раньше
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await jira_closure.apply_closures(session)
    assert await _notes() == [] and (await _fresh(Booking, env.closed.id)).status == BookingStatus.returned
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None


# ---------- «Возврат ПК» закрыта в Jira ----------

async def _waiting_return(session, env):  # noqa: F811
    comp = await _fresh(Computer, env.closed.computer_id)
    comp = await session.merge(comp)
    comp.status = ComputerStatus.cleaning
    env.closed.returned_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await session.commit()
    return await _task(session, env, env.closed, kind="return")


async def test_return_done_in_jira_frees_the_pc(session, env, sd):  # noqa: F811
    req = await _waiting_return(session, env)
    sd.details = real_sd.SdDetails(taken=True, resolution="Done", closed_by=("worker", ""))
    await jira_closure.apply_closures(session)
    assert (await _fresh(Computer, env.closed.computer_id)).status == ComputerStatus.available
    (event,) = [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.cleaned]
    assert (event.actor_id, event.booking_id) == (env.worker.id, env.closed.id)
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None


async def test_return_rejected_in_jira_does_not_free_the_pc(session, env, sd):  # noqa: F811
    req = await _waiting_return(session, env)
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await jira_closure.apply_closures(session)
    assert (await _fresh(Computer, env.closed.computer_id)).status == ComputerStatus.cleaning
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None


async def test_old_return_task_does_not_free_pc_returned_again(session, env, sd, make_department):  # noqa: F811
    """ПК вернули повторно: закрытие задачи по старому возврату не должно освобождать ПК, ждущий новой очистки."""
    from tests.sync_fakes import add_booking
    old = await _task(session, env, env.closed, kind="return")
    comp = await session.merge(await _fresh(Computer, env.closed.computer_id))
    comp.status = ComputerStatus.cleaning
    newer = await add_booking(session, comp, env.owner, await make_department("Ops"), status="returned",
                              returned_at=datetime.now(timezone.utc))
    assert newer.id != env.closed.id
    await jira_closure.apply_closures(session)
    assert (await _fresh(Computer, env.closed.computer_id)).status == ComputerStatus.cleaning
    assert (await _fresh(ServiceRequest, old.id)).handled_at is not None


async def test_return_closed_when_pc_is_not_waiting_does_nothing(session, env, sd):  # noqa: F811
    await _task(session, env, env.closed, kind="return")  # ПК уже свободен
    await jira_closure.apply_closures(session)
    assert await _notes() == []
    assert not [e for e in (await session.scalars(select(AssetEvent))).all() if e.event_type == EventType.cleaned]


# ---------- выбор задач и сбои ----------

async def test_only_unhandled_closed_prepare_and_return_tasks_are_taken(session, env, sd):  # noqa: F811
    handled = await _task(session, env, env.early, handled_at=datetime.now(timezone.utc))
    await _task(session, env, env.early, status="In Progress", status_category="indeterminate")
    await _task(session, env, env.early, kind="problem")
    await _task(session, env, env.early, kind="diagnose")
    await jira_closure.apply_closures(session)
    assert sd.details_calls == []
    assert (await _fresh(ServiceRequest, handled.id)).handled_at is not None


async def test_jira_failure_leaves_task_for_next_round(session, env, sd, caplog):  # noqa: F811
    req = await _task(session, env, env.early)
    sd.details_error = boom("Service Desk недоступен")
    await jira_closure.apply_closures(session)
    assert (await _fresh(ServiceRequest, req.id)).handled_at is None
    assert "повтор в следующий круг" in caplog.text
    assert (await _fresh(Booking, env.early.id)).status == BookingStatus.active

    sd.details_error = None
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await jira_closure.apply_closures(session)
    assert (await _fresh(Booking, env.early.id)).status == BookingStatus.cancelled


async def test_race_with_portal_is_marked_handled(session, env, sd, monkeypatch):  # noqa: F811
    """Пока разбирали закрытие, заказ уже отклонили в портале: Conflict не повторяется бесконечно."""
    req = await _task(session, env, env.early)
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    from app.core.errors import Conflict

    async def lost_race(*a, **k):
        raise Conflict("Заказ уже закрыт")
    monkeypatch.setattr(jira_closure.executor, "reject", lost_race)
    await jira_closure.apply_closures(session)
    assert (await _fresh(ServiceRequest, req.id)).handled_at is not None


async def test_nothing_happens_without_service_desk(session, env, sd, monkeypatch):  # noqa: F811
    from app.core.config import settings
    req = await _task(session, env, env.early)
    monkeypatch.setattr(settings, "sd_token", "")
    await jira_closure.apply_closures(session)
    assert (await _fresh(ServiceRequest, req.id)).handled_at is None


# ---------- портал закрывает «Возврат ПК» после очистки ----------

async def test_portal_closes_return_task_after_cleaning(session, env, sd):  # noqa: F811
    req = await _task(session, env, env.closed, kind="return", status="В работе", status_category="indeterminate")
    sd.status = real_sd.SdStatus("В работе", "indeterminate")
    await service_requests.refresh_open(session)
    assert sd.closed == []  # диск ещё не очищен

    session.add(AssetEvent(computer_id=env.closed.computer_id, booking_id=env.closed.id, event_type=EventType.cleaned,
                           message="диск очищен", payload={}))
    await session.commit()
    async with SessionLocal() as other:
        (await other.get(ServiceRequest, req.id)).last_checked_at = None
        await other.commit()
    await service_requests.refresh_open(session)
    assert sd.closed == [("DR-7", "Done")]
    assert (await _fresh(ServiceRequest, req.id)).status_category == "done"
    before = len(await _notes())  # «Заявка DR-7: Выполнен» о смене статуса
    await jira_closure.apply_closures(session)  # портал сам закрыл: реагировать не на что
    assert len(await _notes()) == before and (await _fresh(ServiceRequest, req.id)).handled_at is not None
