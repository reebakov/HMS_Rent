"""Сервис заявок в Service Desk (app/services/service_requests.py) на реальной PostgreSQL.

Клиент Jira подменяется: app.services.service_requests.sd -> FakeSd.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core import clock
from app.core.config import settings
from app.core.errors import DomainError, Forbidden, NotFound
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.models import Booking, Notification, NotificationKind, ServiceRequest, UserRole, VirtualMachine
from app.schemas.service_request import BuildCreate, earliest_wanted_by
from app.schemas.settings import default_pc_builds
from app.services import service_requests as svc

from .sync_fakes import add_booking


def _now() -> datetime:
    """Текущее время в момент вызова: константа при импорте старела за время прогона и ломала проверки «свежая заявка»."""
    return datetime.now(timezone.utc)


class FakeSd:
    """Подмена модуля servicedesk: запоминает вызовы, ответы и ошибки задаются в тесте."""

    ServiceDeskError = real_sd.ServiceDeskError
    RESOLUTION_DONE = real_sd.RESOLUTION_DONE
    RESOLUTION_REJECTED = real_sd.RESOLUTION_REJECTED
    is_done_transition = staticmethod(real_sd.is_done_transition)

    def __init__(self):
        self.created: list[tuple] = []
        self.available: list[dict] = []  # переходы, доступные из текущего статуса
        self.transitions_error: Exception | None = None
        self.moved: list[tuple] = []
        self.move_error: Exception | None = None
        self.updated: list[tuple] = []
        self.update_error: Exception | None = None
        self.create_error: Exception | None = None
        self.status = real_sd.SdStatus("Ожидает поддержки", "new")
        self.status_errors: dict[str, Exception] = {}
        self.status_calls: list[str] = []
        self.comments = [real_sd.SdComment("Админ", "Привет", "2026-01-01T10:00:00+0000", False)]
        self.comments_error: Exception | None = None
        self.details = real_sd.SdDetails(taken=False, resolution=None)
        self.details_error: Exception | None = None
        self.details_calls: list[str] = []
        self.closed: list[tuple] = []
        self.close_error: Exception | None = None
        self.close_result = True
        self.sent: list[tuple] = []
        self.send_error: Exception | None = None

    async def create_request(self, type_id, description, on_behalf_of=None):
        self.created.append((type_id, None, description, on_behalf_of))  # тема появится после update_issue
        if self.create_error:
            raise self.create_error
        return f"HMS-{len(self.created)}", self.status

    async def transitions(self, key):
        if self.transitions_error:
            raise self.transitions_error
        return self.available

    async def transition_issue(self, key, transition_id, resolution=None):
        if self.move_error:
            raise self.move_error
        self.moved.append((key, transition_id, resolution))

    async def update_issue(self, key, fields):
        if self.update_error:
            raise self.update_error
        self.updated.append((key, fields))
        if "summary" in fields:  # Jira хранит тему: подставляем её в запись о созданной заявке
            i = int(key.split("-")[1]) - 1
            type_id, _, description, behalf = self.created[i]
            self.created[i] = (type_id, fields["summary"], description, behalf)

    async def get_status(self, key):
        self.status_calls.append(key)
        if key in self.status_errors:
            raise self.status_errors[key]
        return self.status

    async def get_details(self, key):
        self.details_calls.append(key)
        if self.details_error:
            raise self.details_error
        return self.details

    async def close_issue(self, key, resolution):
        if self.close_error:
            raise self.close_error
        self.closed.append((key, resolution))
        self.status = real_sd.SdStatus("Done", "done")  # закрыли мы или успел исполнитель — в Jira теперь Done
        return self.close_result

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
                     sd_request_type=1252, sd_return_on_return=True, sd_issue_fields={}).items():
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
    vm = VirtualMachine(name="A1007", cpu=4, ram_gb=8, disk_gb=100, os_label="Ubuntu 22.04", status="ready",
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


# ---------- шапка задачи после создания ----------

HEADER = {"components": [{"name": "HMS"}], "customfield_10002": "DR-69"}


async def _all_kinds(session, env, sd):
    await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Не включается")
    await svc.create_return(session, env.booking.id, env.owner)
    await svc.create_prepare(session, env.booking.id, env.owner)
    session.add(svc.new_diagnose(await session.get(Booking, env.booking.id), None, env.owner, "Не включается"))
    await session.commit()
    await svc.send_diagnose(session, env.booking.computer_id, env.owner)
    await svc.create_build(session, env.owner, BuildCreate(build=default_pc_builds()[0], os_label="Windows 11 26H2",
                                                           requester_nick="ivan",
                                                           expected_return_at=clock.today() + timedelta(days=30)))


async def test_all_requests_go_through_one_type_and_get_the_same_header(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_issue_fields", HEADER)
    monkeypatch.setattr(settings, "sd_request_type", 1252)
    await _all_kinds(session, env, sd)
    assert {c[0] for c in sd.created} == {1252} and len(sd.created) == 5
    assert [key for key, _ in sd.updated] == [f"HMS-{i}" for i in range(1, 6)]
    for (_, fields), (_, summary, _, _) in zip(sd.updated, sd.created, strict=True):
        assert fields == {"summary": summary, **HEADER}  # тема заявки, компонент и эпик — у каждой задачи
        assert summary.startswith("HMS Rent: ")


async def test_summary_is_set_after_creation_not_in_the_form(session, env, sd, monkeypatch):
    """В форме «Прочее» темы нет: создаётся только описание, тема уходит отдельной правкой (с префиксом ТЕСТ, если задан)."""
    monkeypatch.setattr(settings, "sd_summary_prefix", "ТЕСТ")
    await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Не включается")
    assert sd.updated[0][1]["summary"].startswith("ТЕСТ HMS Rent: проблема с ПК A001")
    assert len(sd.updated[0][1]["summary"]) <= 255


async def test_header_without_configured_fields_still_sets_summary(session, env, sd):
    await _all_kinds(session, env, sd)
    assert all(set(fields) == {"summary"} for _, fields in sd.updated)


async def test_header_failure_does_not_cancel_request(session, env, sd, monkeypatch, caplog):
    monkeypatch.setattr(settings, "sd_issue_fields", HEADER)
    sd.update_error = boom("Service Desk 400: components: не найден")
    req = await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Не включается")
    assert (req.issue_key, req.error) == ("HMS-1", None)  # задача создана и сохранена
    assert "Шапка задачи HMS-1 не изменена" in caplog.text


# ---------- create_problem ----------

async def test_create_problem_for_booking(session, env, sd):
    req = await svc.create_problem(session, env.owner, booking_id=env.booking.id, vm_id=None, message="Не включается")
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (1252, "owner")
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
    assert "A1007" in summary and "заказ №555" in summary
    for part in ["Нет сети", "Виртуалка: A1007 (Ubuntu 22.04)", "Заказ №555", "4 CPU · 8 ГБ · 100 ГБ, IP: 10.0.0.5, статус: ready",
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
    monkeypatch.setattr(settings, "sd_request_type", 7777)
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


async def test_list_for_user_author_of_order_for_other_team_sees_its_requests(session, env, sd, make_computer):
    """Заказ можно оформить на другую команду: его автор видит заявки по нему, как и участники этой команды."""
    comp = await make_computer("A002")
    booking = await add_booking(session, comp, env.stranger, env.qa)  # автор из Ops, команда-получатель QA
    req = await add_req(session, env.mate, booking=booking)
    assert [r.id for r in await svc.list_for_user(session, env.stranger)] == [req.id]
    assert (await svc.get_with_comments(session, env.stranger, req.id))[0].id == req.id


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


async def test_customer_status_from_jira_status():
    """Статусы workflow DR переводятся в слова для заказчика; чужие статусы остаются как есть."""
    expected = {
        "Backlog": "Принят", "To Do": "Принят", "In Progress": "В работе", "Validation": "В работе",
        "Escalated": "В работе", "Frozen": "Заморожено", "Done": "Выполнен", "Ожидает поддержки": "Ожидает поддержки",
    }
    for jira, shown in expected.items():
        assert ServiceRequest(status=jira).customer_status == shown, jira
    assert ServiceRequest(status=None).customer_status is None


@pytest.mark.parametrize("jira, shown", [
    ("Сделать", "Принят"), ("В работе", "В работе"), ("Заморожено", "Заморожено"), ("Готово", "Выполнен"),
    ("Передано в разработку", "В работе"), ("Backlog", "Принят"), ("Validation", "В работе"),
])
async def test_customer_status_understands_translated_jira_names(jira, shown):
    """Сервисная учётка может получать названия статусов проекта DR по-русски."""
    assert ServiceRequest(status=jira).customer_status == shown


async def test_translated_names_keep_taken_back_note_and_cancel_rules():
    assert ServiceRequest(status="Заморожено", status_note="Ждём SSD").customer_note == "Ждём SSD"
    assert ServiceRequest(status="Сделать", was_taken=True).customer_status == "Снято с исполнителя"


@pytest.mark.parametrize("status, category, taken, resolution, shown", [
    ("Backlog", "new", True, None, "Снято с исполнителя"),
    ("To Do", "new", True, None, "Снято с исполнителя"),
    ("In Progress", "indeterminate", True, None, "В работе"),  # снова взяли — прежнее «снято» не мешает
    ("Done", "done", True, "Done", "Выполнен"),
    ("Done", "done", True, "Rejected", "Отклонён"),
])
async def test_customer_status_uses_history_and_resolution(status, category, taken, resolution, shown):
    req = ServiceRequest(status=status, status_category=category, was_taken=taken, resolution=resolution)
    assert req.customer_status == shown


async def test_customer_note_only_for_frozen():
    assert ServiceRequest(status="Frozen", status_note="Ждём SSD").customer_note == "Ждём SSD"
    assert ServiceRequest(status="In Progress", status_note="Ждём SSD").customer_note is None


async def test_refresh_open_backlog_after_work_is_taken_back(session, env, sd):
    """Задачу брали и вернули в Backlog между опросами: это видно только по истории Jira."""
    req = await add_req(session, env.owner, key="HMS-7", status="Backlog", status_category="new")
    sd.status = real_sd.SdStatus("Backlog", "new")
    sd.details = real_sd.SdDetails(taken=True, resolution=None)
    await svc.refresh_open(session)
    assert (await fresh(req.id)).was_taken is True
    (note,) = await _notes()
    assert note.title == "Заявка HMS-7: Снято с исполнителя"


async def test_refresh_open_taken_flag_is_kept(session, env, sd):
    req = await add_req(session, env.owner, key="HMS-7", status="Backlog", status_category="new", was_taken=True)
    sd.status = real_sd.SdStatus("Backlog", "new")
    await svc.refresh_open(session)
    assert sd.details_calls == []  # уже известно: историю не читаем
    assert (await fresh(req.id)).was_taken is True


async def test_refresh_open_frozen_keeps_last_staff_comment(session, env, sd):
    req = await add_req(session, env.owner, key="HMS-7", status="In Progress", status_category="indeterminate")
    sd.status = real_sd.SdStatus("Frozen", "indeterminate")
    sd.comments = [real_sd.SdComment("Олег", "Первый", None, False), real_sd.SdComment("Олег", "Ждём SSD", None, False),
                   real_sd.SdComment("Иван", "Когда?", None, True)]  # свой комментарий с портала не берём
    await svc.refresh_open(session)
    saved = await fresh(req.id)
    assert (saved.status_note, saved.customer_note) == ("Ждём SSD", "Ждём SSD")
    (note,) = await _notes()
    assert (note.title, note.body) == ("Заявка HMS-7: Заморожено", "Ждём SSD")

    sd.status = real_sd.SdStatus("In Progress", "indeterminate")
    async with SessionLocal() as other:  # снова «устарела» — worker опросит заявку ещё раз
        (await other.get(ServiceRequest, req.id)).last_checked_at = None
        await other.commit()
    await svc.refresh_open(session)
    assert (await fresh(req.id)).status_note is None  # разморозили — комментарий больше не показывается


async def test_refresh_open_reads_resolution_of_closed_task(session, env, sd):
    req = await add_req(session, env.owner, key="HMS-7", status="In Progress", status_category="indeterminate")
    sd.status = real_sd.SdStatus("Done", "done")
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await svc.refresh_open(session)
    saved = await fresh(req.id)
    assert (saved.resolution, saved.customer_status) == ("Rejected", "Отклонён")


async def test_refresh_open_without_history_access_still_updates_status(session, env, sd, caplog):
    """У сервисной учётки нет прав на REST Jira: статус обновляется, заказчик видит название из Jira."""
    req = await add_req(session, env.owner, key="HMS-7", status="Backlog", status_category="new")
    sd.status = real_sd.SdStatus("Backlog", "new")
    sd.details_error = boom("Service Desk 403: нет прав")
    await svc.refresh_open(session)
    saved = await fresh(req.id)
    assert (saved.status, saved.was_taken, saved.customer_status) == ("Backlog", False, "Принят")
    assert saved.last_checked_at is not None and "история и комментарий не получены" in caplog.text


# ---------- закрытие задач «подготовить ПК» ----------

async def _prepare_req(session, env, **booking_fields):
    for k, v in booking_fields.items():
        setattr(env.booking, k, v)
    return await add_req(session, env.owner, booking=env.booking, kind="prepare", key="DR-7", status="In Progress",
                         status_category="indeterminate")


async def test_prepared_order_closes_task_as_done(session, env, sd):
    req = await _prepare_req(session, env, prepared_at=_now())
    await svc.refresh_open(session)
    assert sd.closed == [("DR-7", "Done")]
    assert (await fresh(req.id)).customer_status == "Выполнен"
    assert await _notes() == []  # «ПК готов» заказчик уже получил, второе уведомление об итоге не нужно


@pytest.mark.parametrize("fields", [{"status": "cancelled"}, {"status": "returned"}], ids=["отклонён", "отменён до подготовки"])
async def test_closed_unprepared_order_closes_task_as_rejected(session, env, sd, fields):
    await _prepare_req(session, env, **fields)
    await svc.refresh_open(session)
    assert sd.closed == [("DR-7", "Rejected")]


async def test_prepared_then_returned_order_is_done_not_rejected(session, env, sd):
    await _prepare_req(session, env, prepared_at=_now(), status="returned")
    await svc.refresh_open(session)
    assert sd.closed == [("DR-7", "Done")]


async def test_waiting_order_keeps_task_open(session, env, sd):
    await _prepare_req(session, env)  # заказ активен, данных подключения ещё нет
    await svc.refresh_open(session)
    assert sd.closed == []


@pytest.mark.parametrize("kind", ["return", "problem", "build", "diagnose"])
async def test_only_prepare_tasks_are_closed_by_portal(session, env, sd, kind):
    env.booking.prepared_at = _now()
    await add_req(session, env.owner, booking=env.booking, kind=kind, key="DR-8", status="In Progress",
                  status_category="indeterminate")
    await svc.refresh_open(session)
    assert sd.closed == []


async def test_task_closed_by_hand_is_left_alone(session, env, sd):
    """Исполнитель закрыл задачу в Jira сам: портал видит категорию done и ничего не меняет."""
    env.booking.prepared_at = _now()
    await add_req(session, env.owner, booking=env.booking, kind="prepare", key="DR-7", status="In Progress",
                  status_category="indeterminate")
    sd.status = real_sd.SdStatus("Done", "done")
    await svc.refresh_open(session)
    assert sd.closed == []


async def test_close_race_with_manual_close_is_harmless(session, env, sd):
    req = await _prepare_req(session, env, prepared_at=_now())
    sd.close_result = False  # между проверкой и переходом задачу закрыли вручную
    await svc.refresh_open(session)
    assert (await fresh(req.id)).status_category == "done"


async def test_close_failure_is_logged_and_retried(session, env, sd, caplog):
    req = await _prepare_req(session, env, prepared_at=_now())
    sd.close_error = boom("Из статуса «Frozen» нет перехода в Done")
    await svc.refresh_open(session)
    assert "Задача DR-7 не закрыта (Done)" in caplog.text
    assert (await fresh(req.id)).status_category != "done"  # останется открытой: следующий круг попробует снова
    sd.close_error = None
    async with SessionLocal() as other:
        (await other.get(ServiceRequest, req.id)).last_checked_at = None
        await other.commit()
    await svc.refresh_open(session)
    assert sd.closed == [("DR-7", "Done")]


async def _notes() -> list[Notification]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(Notification).order_by(Notification.id))).all())


async def test_refresh_open_notifies_author_when_status_changes(session, env, sd):
    await add_req(session, env.owner, key="HMS-7", status="Ожидает поддержки", status_category="new")
    sd.status = real_sd.SdStatus("Решено", "done")
    await svc.refresh_open(session)
    (note,) = await _notes()
    assert (note.user_id, note.kind, note.title) == (env.owner.id, NotificationKind.request_status, "Заявка HMS-7: Решено")
    assert note.body == "s"  # тема заявки


async def test_refresh_open_does_not_notify_on_first_status_or_same_status(session, env, sd):
    await add_req(session, env.owner, key="HMS-1")  # статус ещё не был известен
    await add_req(session, env.owner, key="HMS-2", status="В работе", status_category="indeterminate")
    sd.status = real_sd.SdStatus("В работе", "indeterminate")
    await svc.refresh_open(session)
    assert await _notes() == []


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


# ---------- create_prepare: «подготовить ПК» после брони ----------

async def test_create_prepare_saves_request_with_os(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_request_type", 4321)
    env.booking.os_label, env.booking.purpose = "Ubuntu 24.04", "Тесты сборки"
    await session.commit()
    await svc.create_prepare(session, env.booking.id, env.mate)
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (4321, "mate")
    assert summary == f"HMS Rent: подготовить ПК A001 (заказ №{env.booking.order_number})"
    assert "ОС: Ubuntu 24.04" in description and "Цель: Тесты сборки" in description
    assert "Компьютер: A001 (ITAM-1)" in description
    [saved] = await rows()
    assert (saved.kind, saved.user_id, saved.booking_id, saved.issue_key) == ("prepare", env.mate.id, env.booking.id, "HMS-1")


async def test_create_prepare_links_executor_order_page(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://hmsrent.test/")
    await svc.create_prepare(session, env.booking.id, env.owner)
    description = sd.created[0][2]
    assert f"на странице заказа: https://hmsrent.test/executor/orders/{env.booking.id}" in description


@pytest.mark.parametrize("prefix, expected", [
    ("", "HMS Rent: подготовить ПК A001"),
    ("ТЕСТ", "ТЕСТ HMS Rent: подготовить ПК A001"),
    ("  ТЕСТ  ", "ТЕСТ HMS Rent: подготовить ПК A001"),
])
async def test_summary_prefix_only_in_jira(session, env, sd, monkeypatch, prefix, expected):
    """SD_SUMMARY_PREFIX помечает проверочные заявки в Jira; в портале тема остаётся без него."""
    monkeypatch.setattr(settings, "sd_summary_prefix", prefix)
    await svc.create_prepare(session, env.booking.id, env.owner)
    assert sd.created[0][1].startswith(f"{expected} (заказ №")
    [saved] = await rows()
    assert saved.summary.startswith("HMS Rent: подготовить ПК A001")


@pytest.mark.parametrize("field, value", [("sd_token", ""), ("sd_prepare_on_booking", False)])
async def test_create_prepare_disabled(session, env, sd, monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    await svc.create_prepare(session, env.booking.id, env.owner)
    assert sd.created == [] and await rows() == []


async def test_create_prepare_unknown_booking_is_silent(session, env, sd):
    await svc.create_prepare(session, 999, env.owner)
    assert sd.created == [] and await rows() == []


async def test_create_prepare_jira_error_is_stored_not_raised(session, env, sd):
    sd.create_error = boom()
    await svc.create_prepare(session, env.booking.id, env.owner)  # не бросает: бронь уже сделана
    [saved] = await rows()
    assert saved.kind == "prepare" and saved.issue_key is None and saved.error == REJECTED


# ---------- create_build: сборка по запросу ----------

def build_data(env, **kw) -> BuildCreate:
    data = {"build": default_pc_builds()[0], "os_label": "Debian 12", "department_id": env.qa.id,
            "requester_nick": "ivan",
            "expected_return_at": clock.today() + timedelta(days=30)}
    return BuildCreate(**(data | kw))


async def test_create_build_typical(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_request_type", 4321)
    wanted = earliest_wanted_by()  # самый ранний допустимый срок: норматив сборки
    req = await svc.create_build(session, env.owner, build_data(env, purpose="Нагрузочные тесты", wanted_by=wanted))
    type_id, summary, description, behalf = sd.created[0]
    assert (type_id, behalf) == (4321, "owner")
    assert summary.startswith("HMS Rent: сборка ПК — тип A (заказ №") and summary.endswith(")")
    for text in (f"Сборка: {default_pc_builds()[0]}", "ОС: Debian 12", "Команда-получатель: QA",
                 "Арендатор: Иван Иванов (ivan), ivan@corp.test", f"Желаемый срок готовности: {wanted:%d.%m.%Y}",
                 "Цель: Нагрузочные тесты"):
        assert text in description
    assert "согласование" not in description
    assert (req.kind, req.user_id, req.department_id, req.booking_id, req.vm_id) == ("build", env.owner.id, env.qa.id,
                                                                                      None, None)
    assert req.issue_key == "HMS-1"


async def test_create_build_custom_and_long_term(session, env, sd):
    far = clock.today() + timedelta(days=200)
    await svc.create_build(session, env.owner, build_data(env, build=None, custom="Ryzen 9, 64 ГБ, RTX 4090",
                                                          expected_return_at=far))
    _, summary, description, _ = sd.created[0]
    assert "своя конфигурация" in summary and "Своя конфигурация: Ryzen 9, 64 ГБ, RTX 4090" in description
    assert f"Срок аренды: до {far:%d.%m.%Y} — дольше 3 месяцев, нужно согласование администратора" in description


async def test_create_build_order_numbers_are_shared_with_bookings(session, env, sd):
    first = await svc.create_build(session, env.owner, build_data(env))
    second = await svc.create_build(session, env.owner, build_data(env))
    n1, n2 = (int(r.summary.rsplit("№", 1)[1].rstrip(")")) for r in (first, second))
    assert n2 == n1 + 1


@pytest.mark.parametrize("kw, error", [
    ({"build": "Z — несуществующая"}, "сборки нет в списке"),
    ({"os_label": "MS-DOS 6.22"}, "ОС нет в списке"),
], ids=["build", "os"])
async def test_create_build_rejects_values_outside_lists(session, env, sd, kw, error):
    with pytest.raises(DomainError, match=error):
        await svc.create_build(session, env.owner, build_data(env, **kw))
    assert sd.created == [] and await rows() == []


async def test_create_build_not_configured(session, env, sd, monkeypatch):
    monkeypatch.setattr(settings, "sd_token", "")
    with pytest.raises(DomainError, match="не подключены"):
        await svc.create_build(session, env.owner, build_data(env))


async def test_create_build_jira_error_not_saved(session, env, sd):
    sd.create_error = boom()
    with pytest.raises(DomainError, match="Не удалось создать заявку"):
        await svc.create_build(session, env.owner, build_data(env))
    assert await rows() == []


@pytest.mark.parametrize("kw", [
    {"build": None, "custom": None}, {"custom": "Ryzen 9, 64 ГБ"}, {"build": None, "custom": "abc"},
    {"wanted_by": clock.today()}, {"wanted_by": earliest_wanted_by() - timedelta(days=1)}, {"expected_return_at": clock.today() - timedelta(days=1)}, {"os_label": " "},
], ids=["none", "both", "short-custom", "wanted-today", "wanted-before-norm", "past", "blank-os"])
def test_build_create_validation(env, kw):
    with pytest.raises(ValidationError):
        build_data(env, **kw)


def test_wanted_by_error_names_the_earliest_date_and_the_norm():
    earliest = earliest_wanted_by()
    with pytest.raises(ValidationError, match=f"не раньше {earliest:%d.%m.%Y}: норматив сборки 3 рабочих дня"):
        BuildCreate(build=default_pc_builds()[0], os_label="Debian 12", requester_nick="i",
                    expected_return_at=clock.today() + timedelta(days=30), wanted_by=earliest - timedelta(days=1))
    assert BuildCreate(build=default_pc_builds()[0], os_label="Debian 12", requester_nick="i",
                       expected_return_at=clock.today() + timedelta(days=30), wanted_by=earliest).wanted_by == earliest


async def test_build_visible_to_team_not_to_strangers(session, env, sd):
    req = await svc.create_build(session, env.owner, build_data(env))
    assert [r.id for r in await svc.list_for_user(session, env.mate)] == [req.id]
    assert await svc.list_for_user(session, env.stranger) == []
    with pytest.raises(Forbidden):
        await svc.get_with_comments(session, env.stranger, req.id)
