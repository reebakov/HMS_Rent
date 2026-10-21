"""Лимит срока аренды (services/term_limit.py) и заявки админу на срок дольше лимита (services/term_requests.py)."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core import clock
from app.core.errors import Conflict, NotFound
from app.db.session import SessionLocal
from app.models import (
    Booking,
    BookingExtension,
    Computer,
    EventType,
    Notification,
    NotificationKind,
    TermRequest,
    TermRequestStatus,
    User,
    UserRole,
    VirtualMachine,
    VmStatus,
)
from app.schemas.booking import BookingCreate, BookingExtend
from app.schemas.vm import VmExtend
from app.services import bookings, runtime, term_limit, term_requests, vms
from app.services.runtime import RuntimeConfig
from tests.test_bookings import events_of
from tests.test_vm_jobs import payload as vm_payload
from tests.test_vm_jobs import vm_on  # noqa: F401 — фикстура: vCenter «настроен», конструктор включён

TODAY = clock.today()
LIMIT = term_limit.add_months(TODAY, term_limit.MAX_TERM_MONTHS)
FAR = LIMIT + timedelta(days=150)  # «хочу ещё на 5 месяцев сверх лимита»


@pytest_asyncio.fixture
async def env(make_department, make_pool, make_user, make_computer):
    dept = await make_department("QA")
    pool = await make_pool("Main")
    user = await make_user("ivanov", department=dept)
    admin = await make_user("boss", role=UserRole.admin.value)
    return SimpleNamespace(dept=dept, pool=pool, user=user, admin=admin, make_computer=make_computer)


async def book(session, env, until: date, user: User | None = None) -> Booking:
    comp = await env.make_computer(pool=env.pool, insight_status="Свободен")
    return await bookings.create_booking(session, user or env.user, BookingCreate(
        computer_id=comp.id, department_id=env.dept.id, requester_name="Иван Иванов", requester_nick="ivan",
        expected_return_at=until))


async def order_vm(session, env, until: date, user: User | None = None) -> VirtualMachine:
    env.vm_count = getattr(env, "vm_count", 0) + 1  # имя ВМ уникально
    return await vms.create_request(session, user or env.user, vm_payload(
        env.dept.id, expected_return_at=until, name=f"dev-box-{env.vm_count}"))


async def requests_of(**filters) -> list[TermRequest]:
    async with SessionLocal() as s:
        q = select(TermRequest).order_by(TermRequest.id)
        for k, v in filters.items():
            q = q.where(getattr(TermRequest, k) == v)
        return list((await s.scalars(q)).unique().all())


async def extensions_of(**filters) -> list[BookingExtension]:
    async with SessionLocal() as s:
        q = select(BookingExtension).order_by(BookingExtension.id)
        for k, v in filters.items():
            q = q.where(getattr(BookingExtension, k) == v)
        return list((await s.scalars(q)).unique().all())


# ---------- арифметика сроков ----------

@pytest.mark.parametrize("day,months,expected", [
    (date(2026, 1, 15), 3, date(2026, 4, 15)),
    (date(2026, 11, 20), 3, date(2027, 2, 20)),      # переход через год
    (date(2026, 5, 31), 3, date(2026, 8, 31)),
    (date(2026, 11, 30), 3, date(2027, 2, 28)),      # в феврале нет 30-го: конец месяца
    (date(2023, 11, 30), 3, date(2024, 2, 29)),      # високосный год
    (date(2026, 12, 31), 3, date(2027, 3, 31)),
])
def test_add_months(day, months, expected):
    assert term_limit.add_months(day, months) == expected


def test_plan_within_limit_needs_no_request(env):
    assert term_limit.plan(env.user, LIMIT) == (LIMIT, False)
    assert term_limit.plan(env.user, TODAY) == (TODAY, False)


def test_plan_over_limit_grants_maximum_and_asks(env):
    assert term_limit.plan(env.user, FAR) == (LIMIT, True)


def test_plan_counts_limit_from_base(env):
    base = TODAY + timedelta(days=40)
    assert term_limit.plan(env.user, FAR, base=base) == (term_limit.add_months(base, 3), True)


def test_plan_overdue_order_counts_limit_from_today(env):
    assert term_limit.plan(env.user, FAR, base=TODAY - timedelta(days=200)) == (LIMIT, True)


def test_plan_admin_is_not_limited(env):
    assert term_limit.plan(env.admin, FAR) == (FAR, False)


def test_plan_second_request_while_first_pending_conflicts(env):
    with pytest.raises(Conflict, match=f"{LIMIT:%d.%m.%Y}.*ждёт решения"):
        term_limit.plan(env.user, FAR, pending=LIMIT)
    assert term_limit.plan(env.user, LIMIT, pending=LIMIT) == (LIMIT, False)  # в пределах лимита заявка не нужна


# ---------- заказ ПК ----------

async def test_booking_within_limit_has_no_request(session, env):
    b = await book(session, env, LIMIT)
    assert b.expected_return_at == LIMIT and b.requested_return_at is None
    assert await requests_of() == []


async def test_booking_over_limit_gets_maximum_and_request(session, env):
    b = await book(session, env, FAR)
    assert b.expected_return_at == LIMIT
    assert b.requested_return_at == FAR
    assert (await session.get(Computer, b.computer_id)).usage_until == LIMIT  # в Insight уходит согласованный срок
    [req] = await requests_of()
    assert (req.booking_id, req.vm_id, req.user_id, req.requested_return_at, req.status) == (
        b.id, None, env.user.id, FAR, TermRequestStatus.pending)


async def test_admin_booking_is_not_limited(session, env):
    b = await book(session, env, FAR, user=env.admin)
    assert b.expected_return_at == FAR and await requests_of() == []


# ---------- продление ПК арендатором ----------

def extend_to(until: date, comment: str | None = None) -> BookingExtend:
    return BookingExtend(expected_return_at=until, comment=comment)


async def test_extend_within_limit_from_current_term(session, env):
    b = await book(session, env, TODAY + timedelta(days=60))
    new = term_limit.add_months(b.expected_return_at, 3)  # лимит продления — от текущего срока, а не от сегодня
    assert new > LIMIT
    b = await bookings.extend_booking(session, env.user, b.id, extend_to(new))
    assert b.expected_return_at == new and b.requested_return_at is None
    assert await requests_of() == []


async def test_extend_over_limit_extends_to_maximum_and_asks(session, env):
    b = await book(session, env, TODAY + timedelta(days=60))
    cap = term_limit.add_months(b.expected_return_at, 3)
    wanted = cap + timedelta(days=90)
    b = await bookings.extend_booking(session, env.user, b.id, extend_to(wanted, "  проект затянулся  "))

    assert b.expected_return_at == cap and b.requested_return_at == wanted
    assert (await session.get(Computer, b.computer_id)).usage_until == cap
    [ext] = await extensions_of(booking_id=b.id)
    assert ext.new_return_at == cap and ext.acknowledged_at is None  # админ видит и продление «Принято», и заявку
    [req] = await requests_of(booking_id=b.id)
    assert (req.requested_return_at, req.comment, req.user_id) == (wanted, "проект затянулся", env.user.id)


async def test_second_request_while_pending_is_rejected_and_changes_nothing(session, env):
    b = await book(session, env, FAR)
    with pytest.raises(Conflict, match="ждёт решения администратора"):
        await bookings.extend_booking(session, env.user, b.id, extend_to(FAR + timedelta(days=400)))
    assert (await session.get(Booking, b.id)).expected_return_at == LIMIT
    assert await extensions_of(booking_id=b.id) == [] and len(await requests_of()) == 1


async def test_extend_within_limit_is_allowed_while_request_pending(session, env):
    b = await book(session, env, FAR)
    b = await bookings.extend_booking(session, env.user, b.id, extend_to(LIMIT + timedelta(days=10)))
    assert b.expected_return_at == LIMIT + timedelta(days=10) and b.requested_return_at == FAR


async def test_admin_extension_is_not_limited(session, env):
    b = await book(session, env, TODAY + timedelta(days=5))
    b = await bookings.extend_booking(session, env.admin, b.id, extend_to(FAR))
    assert b.expected_return_at == FAR and await requests_of() == []


# ---------- заказ и продление ВМ ----------

async def test_vm_over_limit_gets_maximum_and_request(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, FAR)
    assert vm.expected_return_at == LIMIT and vm.requested_return_at == FAR
    [req] = await requests_of()
    assert (req.vm_id, req.booking_id, req.requested_return_at) == (vm.id, None, FAR)


async def test_vm_within_limit_has_no_request(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, LIMIT)
    assert vm.requested_return_at is None and await requests_of() == []


async def test_vm_extend_over_limit_extends_to_maximum_and_asks(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, TODAY + timedelta(days=30))
    cap = term_limit.add_months(vm.expected_return_at, 3)
    wanted = cap + timedelta(days=30)
    vm = await vms.extend(session, env.user, vm.id, VmExtend(expected_return_at=wanted, comment="ещё сборка"))

    assert vm.expected_return_at == cap and vm.requested_return_at == wanted
    [req] = await requests_of(vm_id=vm.id)
    assert (req.requested_return_at, req.comment) == (wanted, "ещё сборка")
    with pytest.raises(Conflict, match="ждёт решения администратора"):
        await vms.extend(session, env.user, vm.id,
                         VmExtend(expected_return_at=term_limit.add_months(cap, 3) + timedelta(days=1)))


async def test_vm_admin_extension_is_not_limited(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, TODAY + timedelta(days=30))
    vm = await vms.extend(session, env.admin, vm.id, VmExtend(expected_return_at=FAR))
    assert vm.expected_return_at == FAR and await requests_of() == []


# ---------- согласование ----------

async def test_approve_booking_sets_requested_term(session, env, monkeypatch):
    monkeypatch.setattr(runtime, "_cache", (0.0, RuntimeConfig(insight_writeback=True)))
    b = await book(session, env, FAR)
    [req] = await requests_of()
    done = await term_requests.approve(session, env.admin, req.id, None)

    assert (done.status, done.decided_by_id) == (TermRequestStatus.approved, env.admin.id) and done.decided_at
    db = await session.get(Booking, b.id, populate_existing=True)
    assert db.expected_return_at == FAR and db.requested_return_at is None
    comp = await session.get(Computer, b.computer_id, populate_existing=True)
    assert comp.usage_until == FAR and comp.writeback_pending is True
    [ext] = await extensions_of(booking_id=b.id)
    assert (ext.old_return_at, ext.new_return_at, ext.user_id, ext.acknowledged_by_id) == (
        LIMIT, FAR, env.admin.id, env.admin.id)
    [ev] = await events_of(b.computer_id, EventType.extended)
    assert ev.actor_id == env.admin.id and f"до {FAR:%d.%m.%Y}" in ev.message


async def test_approve_with_own_date(session, env):
    b = await book(session, env, FAR)
    [req] = await requests_of()
    own = LIMIT + timedelta(days=45)
    await term_requests.approve(session, env.admin, req.id, own)
    assert (await session.get(Booking, b.id, populate_existing=True)).expected_return_at == own


async def test_approved_request_frees_the_slot_for_a_new_one(session, env):
    b = await book(session, env, FAR)
    [req] = await requests_of()
    await term_requests.approve(session, env.admin, req.id, LIMIT + timedelta(days=45))
    again = FAR + timedelta(days=200)
    b = await bookings.extend_booking(session, env.user, b.id, extend_to(again))
    assert b.requested_return_at == again and len(await requests_of(status="pending")) == 1


async def test_approve_date_not_later_than_current_conflicts_and_keeps_request(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    with pytest.raises(Conflict, match="позже текущего"):
        await term_requests.approve(session, env.admin, req.id, LIMIT)
    assert (await requests_of())[0].status == TermRequestStatus.pending


async def test_approve_date_in_past_conflicts(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    with pytest.raises(Conflict, match="в прошлом"):
        await term_requests.approve(session, env.admin, req.id, TODAY - timedelta(days=1))


async def test_approve_returned_booking_conflicts(session, env):
    b = await book(session, env, FAR)
    await bookings.return_booking(session, env.user, b.id, None)
    [req] = await requests_of()
    with pytest.raises(Conflict, match="закрыто"):
        await term_requests.approve(session, env.admin, req.id, None)


async def test_decided_request_cannot_be_decided_again(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    await term_requests.approve(session, env.admin, req.id, None)
    for action in (term_requests.approve(session, env.admin, req.id, None), term_requests.reject(session, env.admin, req.id)):
        with pytest.raises(Conflict, match="уже обработана"):
            await action


async def test_decide_unknown_request_not_found(session, env):
    with pytest.raises(NotFound):
        await term_requests.approve(session, env.admin, 999, None)
    with pytest.raises(NotFound):
        await term_requests.reject(session, env.admin, 999)


async def test_approve_vm_sets_requested_term(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, FAR)
    [req] = await requests_of()
    await term_requests.approve(session, env.admin, req.id, None)
    db = await session.get(VirtualMachine, vm.id, populate_existing=True)
    assert db.expected_return_at == FAR and db.requested_return_at is None
    [ext] = await extensions_of(vm_id=vm.id)
    assert (ext.new_return_at, ext.acknowledged_by_id) == (FAR, env.admin.id)


async def test_approve_deleted_vm_conflicts(session, env, vm_on):  # noqa: F811
    vm = await order_vm(session, env, FAR)
    [req] = await requests_of()
    vm.status = VmStatus.deleted.value
    await session.commit()
    with pytest.raises(Conflict, match="удалена"):
        await term_requests.approve(session, env.admin, req.id, None)


async def test_reject_keeps_granted_term(session, env):
    b = await book(session, env, FAR)
    [req] = await requests_of()
    done = await term_requests.reject(session, env.admin, req.id)

    assert (done.status, done.decided_by_id) == (TermRequestStatus.rejected, env.admin.id)
    db = await session.get(Booking, b.id, populate_existing=True)
    assert db.expected_return_at == LIMIT and db.requested_return_at is None
    assert await extensions_of(booking_id=b.id) == []


async def _notes() -> list[Notification]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(Notification).order_by(Notification.id))).all())


async def test_approve_notifies_requester(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    await term_requests.approve(session, env.admin, req.id, None)
    (note,) = await _notes()
    assert (note.user_id, note.kind) == (env.user.id, NotificationKind.term_decision)
    assert note.title.startswith("Срок ПК ") and note.title.endswith(f"согласован до {FAR:%d.%m.%Y}")


async def test_reject_notifies_requester(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    await term_requests.reject(session, env.admin, req.id)
    (note,) = await _notes()
    assert (note.user_id, note.kind) == (env.user.id, NotificationKind.term_decision)
    assert note.title.endswith("не согласован") and f"до {LIMIT:%d.%m.%Y}" in note.body


async def test_failed_approve_creates_no_notification(session, env):
    await book(session, env, FAR)
    [req] = await requests_of()
    with pytest.raises(Conflict):
        await term_requests.approve(session, env.admin, req.id, TODAY - timedelta(days=1))
    assert await _notes() == []


# ---------- список ----------

async def test_list_pending_oldest_first_without_closed_orders(session, env, vm_on):  # noqa: F811
    first = await book(session, env, FAR)
    closed = await book(session, env, FAR)
    vm = await order_vm(session, env, FAR)
    gone = await order_vm(session, env, FAR)
    done = await book(session, env, FAR)
    await bookings.return_booking(session, env.user, closed.id, None)
    gone.status = VmStatus.deleted.value
    await session.commit()
    [done_req] = await requests_of(booking_id=done.id)
    await term_requests.reject(session, env.admin, done_req.id)

    listed = await term_requests.list_pending(session)
    assert [(r.kind, r.booking_id or r.vm_id) for r in listed] == [("pc", first.id), ("vm", vm.id)]
    assert listed[0].name == first.computer.name and listed[1].name == vm.name


# ---------- API ----------

async def test_api_booking_over_limit_exposes_requested_term(client, login, api, env):
    comp = await env.make_computer(pool=env.pool, insight_status="Свободен")
    login(env.user)
    r = await client.post(api("/bookings"), json={
        "computer_id": comp.id, "department_id": env.dept.id, "requester_name": "Иван Иванов",
        "requester_nick": "ivan", "expected_return_at": FAR.isoformat()})
    assert r.status_code == 201, r.text
    assert (r.json()["expected_return_at"], r.json()["requested_return_at"]) == (LIMIT.isoformat(), FAR.isoformat())
    mine = (await client.get(api("/bookings/my"))).json()
    assert mine[0]["requested_return_at"] == FAR.isoformat()


async def test_api_admin_lists_approves_and_rejects(client, login, api, session, env):
    first, second = await book(session, env, FAR), await book(session, env, FAR)
    login(env.admin)
    [a, b] = (await client.get(api("/admin/term-requests"))).json()
    assert (a["kind"], a["name"], a["requested_return_at"], a["user"]["username"]) == (
        "pc", first.computer.name, FAR.isoformat(), "ivanov")
    assert (a["current_return_at"], a["department"]["name"], a["requester_nick"], a["order_number"]) == (
        LIMIT.isoformat(), "QA", "ivan", first.order_number)

    own = (LIMIT + timedelta(days=20)).isoformat()
    r = await client.post(api(f"/admin/term-requests/{a['id']}/approve"), json={"approved_return_at": own})
    assert r.status_code == 200, r.text
    assert (await session.get(Booking, first.id, populate_existing=True)).expected_return_at.isoformat() == own

    assert (await client.post(api(f"/admin/term-requests/{b['id']}/reject"))).status_code == 200
    assert (await client.get(api("/admin/term-requests"))).json() == []
    assert (await client.post(api(f"/admin/term-requests/{b['id']}/reject"))).status_code == 409
    assert (await client.post(api("/admin/term-requests/999/approve"), json={})).status_code == 404
    assert (await session.get(Booking, second.id, populate_existing=True)).expected_return_at == LIMIT


@pytest.mark.parametrize("body", [{"approved_return_at": "2020-01-01"}, {"approved_return_at": "не дата"}],
                         ids=["past", "garbage"])
async def test_api_approve_validation_422(client, login, api, session, env, body):
    await book(session, env, FAR)
    [req] = await requests_of()
    login(env.admin)
    assert (await client.post(api(f"/admin/term-requests/{req.id}/approve"), json=body)).status_code == 422
    assert (await requests_of())[0].status == TermRequestStatus.pending
