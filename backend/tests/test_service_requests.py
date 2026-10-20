"""Сервис заявок в Service Desk (app/services/service_requests.py) на реальной PostgreSQL.

Клиент Jira подменяется: app.services.service_requests.sd -> FakeSd.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.config import settings
from app.core.errors import DomainError, Forbidden, NotFound
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import ServiceRequest, UserRole, VirtualMachine
from app.services import service_requests as svc

from .sync_fakes import add_booking


def _now() -> datetime:
    """Текущее время в момент вызова: константа при импорте старела за время прогона и ломала проверки «свежая заявка»."""
    return datetime.now(timezone.utc)


class FakeSd:
    """Подмена модуля servicedesk: запоминает вызовы, ответы и ошибки задаются в тесте."""

    ServiceDeskError = real_sd.ServiceDeskError

    def __init__(self):
        self.created: list[tuple] = []
        self.create_error: Exception | None = None
        self.status = real_sd.SdStatus("Ожидает поддержки", "new")
        self.status_errors: dict[str, Exception] = {}
        self.status_calls: list[str] = []
        self.comments = [real_sd.SdComment("Админ", "Привет", "2026-01-01T10:00:00+0000", False)]
        self.comments_error: Exception | None = None
        self.sent: list[tuple] = []
        self.send_error: Exception | None = None

    async def create_request(self, type_id, summary, description, on_behalf_of=None):
        self.created.append((type_id, summary, description, on_behalf_of))
        if self.create_error:
            raise self.create_error
        return f"HMS-{len(self.created)}", self.status

    async def get_status(self, key):
        self.status_calls.append(key)
        if key in self.status_errors:
            raise self.status_errors[key]
        return self.status

    async def get_comments(self, key):
        if self.comments_error:
            raise self.comments_error
        return self.comments

    async def add_comment(self, key, author, text):
        self.sent.append((key, author, text))
        if self.send_error:
            raise self.send_error


def boom(text="Service Desk 500: boom") -> Exception:
    return real_sd.ServiceDeskError(text)


REJECTED = "Service Desk отклонил запрос, попробуйте позже"


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSd()
    monkeypatch.setattr(svc, "sd", fake)
    for k, v in dict(sd_jira_url="https://jira.test", sd_token="tok", sd_username="", sd_password="",
                     sd_request_type_problem=1248, sd_request_type_return=1252, sd_return_on_return=True).items():
        monkeypatch.setattr(settings, k, v)
    return fake


@pytest_asyncio.fixture
async def env(session, make_department, make_user, make_pool, make_computer):
    """Команда QA (владелец, коллега, админ), чужая команда Ops, ПК с характеристиками, бронь и виртуалка владельца."""
    qa, ops = await make_department("QA"), await make_department("Ops")
    owner = await make_user("owner", department=qa, display_name="Иван Иванов", email="ivan@corp.test")
    mate = await make_user("mate", department=qa)
    stranger = await make_user("stranger", department=ops)
    nodept = await make_user("nodept")
    admin = await make_user("admin", role=UserRole.admin.value, department=ops)
    comp = await make_computer("A001", await make_pool(), insight_key="ITAM-1", cpu="i9", ram_gb=64,
                               storage="2 TB", gpu="RTX 4090")
    booking = await add_booking(session, comp, owner, qa, requester_name="Иван Иванов", requester_nick="ivan")
    vm = VirtualMachine(name="rent-vm1", cpu=4, ram_gb=8, disk_gb=100, os_label="Ubuntu 22.04", status="ready",
                        order_number=555, user_id=owner.id, department_id=qa.id, requester_name="Иван Иванов",
                        requester_nick="ivan", ip_address="10.0.0.5", attrs={})
    session.add(vm)
    await session.commit()
    return SimpleNamespace(qa=qa, ops=ops, owner=owner, mate=mate, stranger=stranger, nodept=nodept, admin=admin,
                           comp=comp, booking=booking, vm=vm)


async def add_req(session, user, *, booking=None, vm=None, key="HMS-100", **kw) -> ServiceRequest:
    kw.setdefault("kind", "problem")
    req = ServiceRequest(user_id=user.id, booking_id=booking.id if booking else None, vm_id=vm.id if vm else None,
                         issue_key=key, summary="s", description="d", **kw)
    session.add(req)
    await session.commit()
    return req


async def rows() -> list[ServiceRequest]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(ServiceRequest).order_by(ServiceRequest.id))).unique().all())


async def fresh(req_id: int) -> ServiceRequest:
    async with SessionLocal() as s:
        return await s.get(ServiceRequest, req_id)


# ---------- create_problem ----------

async def test_create_problem_for_booking(session, env, sd):
    req = await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Не включается")
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (1248, "owner")
    assert "A001" in summary and f"заказ №{env.booking.order_number}" in summary
    assert description.startswith("Не включается\n\n---\n")
    for part in ["Компьютер: A001 (ITAM-1)", f"Заказ №{env.booking.order_number}", "i9 · 64 ГБ · 2 TB · RTX 4090",
                 "Команда-получатель: QA", "Арендатор: Иван Иванов (ivan)", "Обращение отправил: Иван Иванов (ivan@corp.test)"]:
        assert part in description
    [saved] = await rows()
    assert (saved.id, saved.kind, saved.user_id, saved.booking_id, saved.vm_id) == (req.id, "problem", env.owner.id, env.booking.id, None)
    assert (saved.issue_key, saved.status, saved.status_category, saved.error) == ("HMS-1", "Ожидает поддержки", "new", None)
    assert saved.last_checked_at is not None and saved.summary == summary and saved.description == description


async def test_create_problem_for_vm(session, env, sd):
    req = await svc.create_problem(session, env.owner, booking_id=None, vm_id=env.vm.id, message="Нет сети")
    _, summary, description, _ = sd.created[0]
    assert "rent-vm1" in summary and "заказ №555" in summary
    for part in ["Нет сети", "Виртуалка: rent-vm1 (Ubuntu 22.04)", "Заказ №555", "4 CPU · 8 ГБ · 100 ГБ, IP: 10.0.0.5, статус: ready",
                 "Команда-получатель: QA", "Арендатор: Иван Иванов (ivan)", "Обращение отправил: Иван Иванов (ivan@corp.test)"]:
        assert part in description
    assert (req.vm_id, req.booking_id, req.issue_key) == (env.vm.id, None, "HMS-1")


async def test_create_problem_author_falls_back_to_username(session, env, sd):
    """Нет почты: в «Обращение отправил» подставляется логин."""
    await svc.create_problem(session, env.mate, booking_id=env.booking.id, vm_id=None, message="Сломалось")
    assert "Обращение отправил: mate (mate)" in sd.created[0][2]


@pytest.mark.parametrize("who, allowed", [
    ("owner", True), ("mate", True), ("admin", True), ("stranger", False), ("nodept", False),
])
@pytest.mark.parametrize("target", ["booking", "vm"])
async def test_create_problem_access(session, env, sd, who, allowed, target):
    kw = {"booking_id": env.booking.id, "vm_id": None} if target == "booking" else {"booking_id": None, "vm_id": env.vm.id}
    user = getattr(env, who)
    if allowed:
        assert (await svc.create_problem(session, user, message="Проблема!", **kw)).issue_key
        assert len(sd.created) == 1
    else:
        with pytest.raises(Forbidden):
            await svc.create_problem(session, user, message="Проблема!", **kw)
        assert sd.created == [] and await rows() == []


async def test_create_problem_not_configured(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_token", "")
    with pytest.raises(DomainError, match="не подключены"):
        await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Проблема!")
    assert sd.created == [] and await rows() == []


@pytest.mark.parametrize("kw, exc", [
    ({"booking_id": 999, "vm_id": None}, NotFound),
    ({"booking_id": None, "vm_id": 999}, NotFound),
    ({"booking_id": None, "vm_id": None}, DomainError),
], ids=["no-booking", "no-vm", "nothing"])
async def test_create_problem_missing_target(session, env, sd, kw, exc):
    with pytest.raises(exc):
        await svc.create_problem(session, env.owner, message="Проблема!", **kw)
    assert sd.created == [] and await rows() == []


async def test_create_problem_jira_error_not_saved(session, env, sd):
    sd.create_error = boom("Service Desk 400: customfield_1: обязательное поле")
    with pytest.raises(DomainError) as e:
        await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Проблема!")
    assert str(e.value) == f"Не удалось создать заявку: {REJECTED}"  # подробностей Jira пользователь не видит
    assert await rows() == []


# ---------- create_return ----------

async def test_create_return_saves_request(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_request_type_return", 7777)  # тип «Возврат» отдельный от «Проблемы»
    env.booking.return_comment = "Всё цело"
    await session.commit()
    await svc.create_return(session, env.booking.id, env.mate)
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (7777, "mate")
    assert "возврат ПК A001" in summary and f"заказ №{env.booking.order_number}" in summary
    assert "Комментарий при возврате: Всё цело" in description and "Вернул: mate (mate)" in description
    assert "Компьютер: A001 (ITAM-1)" in description
    [saved] = await rows()
    assert (saved.kind, saved.user_id, saved.booking_id, saved.issue_key, saved.error) == ("return", env.mate.id, env.booking.id, "HMS-1", None)
    assert saved.status_category == "new" and saved.last_checked_at is not None


async def test_create_return_without_comment(session, env, sd):
    await svc.create_return(session, env.booking.id, env.owner)
    assert "Комментарий при возврате" not in sd.created[0][2]


@pytest.mark.parametrize("field, value", [("sd_token", ""), ("sd_return_on_return", False)])
async def test_create_return_disabled(session, env, sd, monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    await svc.create_return(session, env.booking.id, env.owner)
    assert sd.created == [] and await rows() == []


async def test_create_return_unknown_booking_is_silent(session, env, sd):
    await svc.create_return(session, 999, env.owner)
    assert sd.created == [] and await rows() == []


async def test_create_return_jira_error_is_stored_not_raised(session, env, sd, caplog):
    sd.create_error = boom("Service Desk 503: " + "x" * 2000)
    await svc.create_return(session, env.booking.id, env.owner)  # не бросает: возврат уже сделан
    [saved] = await rows()
    assert saved.kind == "return" and saved.issue_key is None and saved.status is None
    assert saved.error == "Service Desk отклонил запрос, попробуйте позже"  # сотруднику — без подробностей Jira
    assert "Service Desk 503: " in caplog.text and "A001" in caplog.text  # подробности — в логе
    assert not saved.is_open  # без ключа заявка не «открытая»


# ---------- list_for_user ----------

async def test_list_for_user_own_and_team_not_foreign(session, env, sd):
    own = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    by_mate = await add_req(session, env.mate, vm=env.vm, key="HMS-2")  # заявка коллеги по ВМ команды
    foreign = await add_req(session, env.stranger, key="HMS-3")  # ни брони, ни ВМ
    assert {r.id for r in await svc.list_for_user(session, env.owner)} == {own.id, by_mate.id}
    assert {r.id for r in await svc.list_for_user(session, env.mate)} == {own.id, by_mate.id}
    assert {r.id for r in await svc.list_for_user(session, env.stranger)} == {foreign.id}


async def test_list_for_user_team_sees_booking_requests_made_by_others(session, env, sd):
    """Заявку по брони команды видит вся команда, даже если создал админ из другой."""
    req = await add_req(session, env.admin, booking=env.booking)
    assert [r.id for r in await svc.list_for_user(session, env.mate)] == [req.id]
    assert await svc.list_for_user(session, env.stranger) == []


async def test_list_for_user_without_department_only_own(session, env, sd):
    own = await add_req(session, env.nodept, key="HMS-1")
    await add_req(session, env.owner, booking=env.booking, key="HMS-2")
    assert [r.id for r in await svc.list_for_user(session, env.nodept)] == [own.id]


async def test_list_for_user_newest_first(session, env, sd):
    old = await add_req(session, env.owner, key="HMS-1")
    new = await add_req(session, env.owner, key="HMS-2")
    old.created_at = _now() - timedelta(days=2)
    new.created_at = _now() - timedelta(days=1)
    await session.commit()
    assert [r.issue_key for r in await svc.list_for_user(session, env.owner)] == ["HMS-2", "HMS-1"]


async def test_list_for_user_limit_200(session, env, sd):
    session.add_all([ServiceRequest(kind="problem", user_id=env.owner.id, summary="s", description="d",
                                    issue_key=f"HMS-{i}", created_at=_now() - timedelta(minutes=i)) for i in range(205)])
    await session.commit()
    got = await svc.list_for_user(session, env.owner)
    assert len(got) == 200 and got[0].issue_key == "HMS-0" and got[-1].issue_key == "HMS-199"


# ---------- get_with_comments ----------

async def test_get_with_comments_updates_status(session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking, status="Старый", status_category="new")
    sd.status = real_sd.SdStatus("Решено", "done")
    got, comments = await svc.get_with_comments(session, env.owner, req.id)
    assert got.id == req.id and comments == sd.comments
    saved = await fresh(req.id)
    assert (saved.status, saved.status_category) == ("Решено", "done") and saved.last_checked_at is not None
    assert sd.status_calls == ["HMS-100"]


async def test_get_with_comments_without_issue_key(session, env, sd):
    req = await add_req(session, env.owner, key=None, kind="return", error="Jira лежит")
    got, comments = await svc.get_with_comments(session, env.owner, req.id)
    assert got.id == req.id and comments == [] and sd.status_calls == []


@pytest.mark.parametrize("what", ["status", "comments"])
async def test_get_with_comments_jira_down(session, env, sd, what):
    req = await add_req(session, env.owner, status="Старый", status_category="new")
    if what == "status":
        sd.status_errors["HMS-100"] = boom()
    else:
        sd.comments_error = boom()
    with pytest.raises(DomainError) as e:
        await svc.get_with_comments(session, env.owner, req.id)
    assert str(e.value) == REJECTED
    if what == "status":
        assert (await fresh(req.id)).status == "Старый"  # статус при сбое не трогаем


@pytest.mark.parametrize("who, ok", [("owner", True), ("mate", True), ("admin", True), ("stranger", False), ("nodept", False)])
async def test_get_with_comments_access(session, env, sd, who, ok):
    req = await add_req(session, env.owner, booking=env.booking)
    if ok:
        assert (await svc.get_with_comments(session, getattr(env, who), req.id))[0].id == req.id
    else:
        with pytest.raises(Forbidden):
            await svc.get_with_comments(session, getattr(env, who), req.id)
        assert sd.status_calls == []


@pytest.mark.parametrize("who, ok", [("owner", True), ("mate", True), ("stranger", False)])
async def test_oldest_request_stays_accessible_beyond_list_limit(session, env, sd, who, ok):
    """В списке — 200 свежих заявок; самая старая не должна становиться «чужой» для автора и команды."""
    oldest = await add_req(session, env.owner, booking=env.booking, key="HMS-1")
    session.add_all(ServiceRequest(kind="problem", user_id=env.owner.id, booking_id=env.booking.id, issue_key=f"HMS-{n}",
                                   summary="s", description="d") for n in range(2, 202))
    await session.commit()
    assert oldest.id not in {r.id for r in await svc.list_for_user(session, env.owner)}
    if ok:
        assert (await svc.get_with_comments(session, getattr(env, who), oldest.id))[0].id == oldest.id
    else:
        with pytest.raises(Forbidden):
            await svc.get_with_comments(session, env.stranger, oldest.id)


async def test_get_with_comments_not_found(session, env, sd):
    with pytest.raises(NotFound):
        await svc.get_with_comments(session, env.owner, 999)


# ---------- add_comment ----------

async def test_add_comment_sends_author_and_text(session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking)
    await svc.add_comment(session, env.mate, req.id, "спасибо")
    assert sd.sent == [("HMS-100", "mate", "спасибо")]  # display_name пользователя mate == логин


async def test_add_comment_uses_display_name(session, env, sd):
    req = await add_req(session, env.owner)
    await svc.add_comment(session, env.owner, req.id, "ok")
    assert sd.sent == [("HMS-100", "Иван Иванов", "ok")]


async def test_add_comment_without_issue_key(session, env, sd):
    req = await add_req(session, env.owner, key=None)
    with pytest.raises(DomainError, match="не была создана"):
        await svc.add_comment(session, env.owner, req.id, "ok")
    assert sd.sent == []


async def test_add_comment_jira_error(session, env, sd):
    req = await add_req(session, env.owner)
    sd.send_error = boom()
    with pytest.raises(DomainError) as e:
        await svc.add_comment(session, env.owner, req.id, "ok")
    assert str(e.value) == f"Не удалось отправить сообщение: {REJECTED}"


async def test_add_comment_access_and_not_found(session, env, sd):
    req = await add_req(session, env.owner, booking=env.booking)
    with pytest.raises(Forbidden):
        await svc.add_comment(session, env.stranger, req.id, "ok")
    with pytest.raises(NotFound):
        await svc.add_comment(session, env.owner, 999, "ok")
    assert sd.sent == []


# ---------- refresh_open ----------

async def test_refresh_open_only_open_and_stale(session, env, sd):
    started = _now()
    stale = started - timedelta(minutes=3)
    never = await add_req(session, env.owner, key="HMS-1")  # ни разу не проверялась
    stale_open = await add_req(session, env.owner, key="HMS-2", status_category="indeterminate", last_checked_at=stale)
    fresh_open = await add_req(session, env.owner, key="HMS-3", status_category="new", last_checked_at=_now() - timedelta(seconds=30))
    done = await add_req(session, env.owner, key="HMS-4", status_category="done", last_checked_at=stale)
    no_key = await add_req(session, env.owner, key=None, kind="return", error="x")
    sd.status = real_sd.SdStatus("Решено", "done")
    await svc.refresh_open(session)
    assert sorted(sd.status_calls) == ["HMS-1", "HMS-2"]
    for r in (never, stale_open):
        saved = await fresh(r.id)
        assert (saved.status, saved.status_category) == ("Решено", "done") and saved.last_checked_at > started
    assert (await fresh(fresh_open.id)).status_category == "new"
    assert (await fresh(done.id)).last_checked_at.replace(microsecond=0) == stale.replace(microsecond=0)
    assert (await fresh(no_key.id)).last_checked_at is None


async def test_refresh_open_not_more_than_once_per_two_minutes(session, env, sd):
    await add_req(session, env.owner, key="HMS-1")
    await svc.refresh_open(session)
    await svc.refresh_open(session)
    assert sd.status_calls == ["HMS-1"]


async def test_refresh_open_rechecks_after_interval(session, env, sd):
    req = await add_req(session, env.owner, key="HMS-1", last_checked_at=_now() - timedelta(minutes=3))
    await svc.refresh_open(session)
    req.last_checked_at = _now() - timedelta(minutes=3)  # прошло ещё две минуты
    await session.commit()
    await svc.refresh_open(session)
    assert sd.status_calls == ["HMS-1", "HMS-1"]


async def test_refresh_open_batch_takes_never_checked_first(session, env, sd):
    old = _now() - timedelta(hours=1)
    await add_req(session, env.owner, key="HMS-OLD1", last_checked_at=old)
    await add_req(session, env.owner, key="HMS-OLD2", last_checked_at=old + timedelta(minutes=1))
    await add_req(session, env.owner, key="HMS-NEW1")
    await add_req(session, env.owner, key="HMS-NEW2")
    await svc.refresh_open(session, batch=3)
    assert sorted(sd.status_calls[:2]) == ["HMS-NEW1", "HMS-NEW2"] and sd.status_calls[2] == "HMS-OLD1"
    assert len(sd.status_calls) == 3


async def test_refresh_open_error_of_one_does_not_block_others(session, env, sd, caplog):
    bad = await add_req(session, env.owner, key="HMS-BAD", status="Было", status_category="new")
    good = await add_req(session, env.owner, key="HMS-GOOD", status_category="new")
    sd.status_errors["HMS-BAD"] = boom()
    sd.status = real_sd.SdStatus("В работе", "indeterminate")
    await svc.refresh_open(session)
    assert sorted(sd.status_calls) == ["HMS-BAD", "HMS-GOOD"]
    saved_bad, saved_good = await fresh(bad.id), await fresh(good.id)
    assert (saved_bad.status, saved_bad.status_category) == ("Было", "new")  # статус не изменился
    assert saved_bad.last_checked_at is not None  # но повторять будем не раньше чем через 2 минуты
    assert (saved_good.status, saved_good.status_category) == ("В работе", "indeterminate")
    assert "HMS-BAD" in caplog.text


async def test_refresh_open_not_configured(session, env, sd, monkeypatch):
    await add_req(session, env.owner, key="HMS-1")
    monkeypatch.setattr(settings, "sd_token", "")
    await svc.refresh_open(session)
    assert sd.status_calls == []
    assert await session.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.last_checked_at.is_not(None))) == 0
