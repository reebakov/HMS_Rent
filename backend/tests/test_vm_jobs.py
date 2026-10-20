"""Виртуалки: заявка (services/vms.py) и фоновые задачи (services/vm_jobs.py). vSphere и Mattermost — фейки."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.db.session import SessionLocal
from app.integrations.vsphere.client import VmInfo, VSphereError
from app.models import BookingExtension, VirtualMachine
from app.schemas.vm import VmCreate, VmExtend, VmOut
from app.services import runtime, vm_jobs, vms

TOMORROW = (clock.today() + timedelta(days=1)).isoformat()  # для JSON-тел запросов


class FakeVSphere:
    """Замена модуля app.integrations.vsphere.client целиком: без pyVmomi и сети."""

    def __init__(self):
        self.create_errors: list[Exception | None] = []  # по одному на вызов create_vm; None — успех
        self.delete_errors: list[Exception | None] = []
        self.created: list[tuple] = []
        self.deleted: list[str] = []  # moid удалённых ВМ
        self.annotations: list[tuple[str, str]] = []  # (moid, текст) каждой записи Notes
        self.annotation_errors: list[Exception | None] = []
        self.existing: dict[str, VmInfo] = {}
        self.ip: str | None = "10.0.0.5"

    def create_vm(self, name, cpu, ram_gb, disk_gb, annotation, template_name=None, customization_spec=None):
        self.created.append((name, cpu, ram_gb, disk_gb, annotation))
        if self.create_errors and (err := self.create_errors.pop(0)):
            raise err
        return VmInfo(moid=f"vm-{len(self.created)}", name=name, power_state="poweredOn", ip_address=self.ip)

    def delete_vm(self, moid):
        self.deleted.append(moid)
        if self.delete_errors and (err := self.delete_errors.pop(0)):
            raise err

    def set_annotation(self, moid, annotation):
        if self.annotation_errors and (err := self.annotation_errors.pop(0)):
            raise err
        self.annotations.append((moid, annotation))

    def vm_status(self, moid):
        return VmInfo(moid=moid, name="x", power_state="poweredOn", ip_address=self.ip)

    def find_vm(self, name):
        return self.existing.get(name)


@pytest.fixture
def vsphere(monkeypatch):
    fake = FakeVSphere()
    monkeypatch.setattr(vm_jobs, "vsphere", fake)
    return fake


@pytest.fixture(autouse=True)
def pauses(monkeypatch):
    """Паузы перед повтором не ждём по-настоящему, но запоминаем, сколько секунд просили."""
    calls: list[float] = []

    async def fake_pause(seconds):
        calls.append(seconds)

    monkeypatch.setattr(vm_jobs, "_pause", fake_pause)
    return calls


@pytest.fixture
def notify(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(vm_jobs, "notify", mock)
    return mock


@pytest.fixture
async def vm_on(session, monkeypatch):
    """vCenter «настроен» и конструктор включён."""
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)
    await runtime.update(session, {"vm_enabled": True})


def payload(dept_id: int, **kw) -> VmCreate:
    data = {"name": "Dev-Box", "cpu": 4, "ram_gb": 8, "disk_gb": 100, "department_id": dept_id,
            "requester_name": "Иван Иванов", "requester_nick": "ivan", "purpose": "тесты",
            "expected_return_at": clock.today() + timedelta(days=30)}
    return VmCreate(**(data | kw))


@pytest.fixture
async def ctx(make_user, make_department):
    dept = await make_department("QA")
    return SimpleNamespace(dept=dept, user=await make_user("ivanov", department=dept))


async def request(session, ctx, **kw) -> VirtualMachine:
    return await vms.create_request(session, ctx.user, payload(ctx.dept.id, **kw))


async def status_of(session, vm) -> VirtualMachine:
    return await vms.get_vm(session, vm.id)


# ---------- заявка ----------

async def test_create_request_ok(session, vm_on, ctx):
    vm = await request(session, ctx)
    assert vm.status == "queued"
    assert vm.name == f"{settings.vm_name_prefix}dev-box"  # префикс + имя пользователя (в нижнем регистре)
    assert (vm.cpu, vm.ram_gb, vm.disk_gb, vm.order_number) == (4, 8, 100, 1)
    assert vm.user_id == ctx.user.id and vm.department_id == ctx.dept.id


async def test_custom_prefix(session, vm_on, ctx, monkeypatch):
    monkeypatch.setattr(settings, "vm_name_prefix", "hms-")
    assert (await request(session, ctx)).name == "hms-dev-box"


async def test_disabled_by_admin_rejected(session, vm_on, ctx):
    await runtime.update(session, {"vm_enabled": False})
    with pytest.raises(Conflict, match="выключен"):
        await request(session, ctx)


async def test_vcenter_not_configured_rejected(session, ctx):
    with pytest.raises(Conflict, match="не подключён"):
        await request(session, ctx)


@pytest.mark.parametrize("field,key,lo,hi", [("cpu", "vm_min_cpu", 2, 8), ("ram_gb", "vm_min_ram_gb", 4, 32),
                                              ("disk_gb", "vm_min_disk_gb", 50, 200)])
async def test_limits_from_runtime_config(session, vm_on, ctx, field, key, lo, hi):
    await runtime.update(session, {"vm_max_per_user": 10})
    for ok in (lo, hi):  # границы включены
        await request(session, ctx, name=f"vm-{field.split('_')[0]}-{ok}", **{field: ok})
    for bad in (lo - 1, hi + 1):
        with pytest.raises(DomainError, match=f"от {lo} до {hi}"):
            await request(session, ctx, name="vm-bad", **{field: bad})


async def test_limits_follow_runtime_update(session, vm_on, ctx):
    await runtime.update(session, {"vm_max_cpu": 16})
    assert (await request(session, ctx, cpu=16)).cpu == 16


async def test_per_user_limit(session, vm_on, ctx, make_user):
    await runtime.update(session, {"vm_max_per_user": 2})
    first = await request(session, ctx, name="vm-one")
    await request(session, ctx, name="vm-two")
    with pytest.raises(Conflict, match="2 из 2"):
        await request(session, ctx, name="vm-three")
    other = await make_user("petrov")  # лимит — на пользователя
    await vms.create_request(session, other, payload(ctx.dept.id, name="vm-other"))
    # удалённая ВМ освобождает место
    await vms.release(session, ctx.user, first.id)  # из очереди -> сразу deleted
    assert (await request(session, ctx, name="vm-three")).status == "queued"


async def test_failed_vm_does_not_count_and_name_is_reusable(session, vm_on, ctx, vsphere, notify):
    await runtime.update(session, {"vm_max_per_user": 1})
    vsphere.create_errors = [RuntimeError("нет места")] * 2
    await request(session, ctx, name="vm-one")
    await vm_jobs.create_next(session)
    again = await request(session, ctx, name="vm-one")  # partial unique index не учитывает failed
    assert again.status == "queued"


async def test_duplicate_name_conflict(session, vm_on, ctx):
    await request(session, ctx, name="vm-one")
    with pytest.raises(Conflict, match="занято"):
        await request(session, ctx, name="VM-ONE")


async def test_unknown_department(session, vm_on, ctx):
    with pytest.raises(DomainError, match="Отдел"):
        await vms.create_request(session, ctx.user, payload(9999))


def test_payload_validation():
    with pytest.raises(ValueError):
        payload(1, name="Bad Name!")
    with pytest.raises(ValueError):
        payload(1, expected_return_at=clock.today() - timedelta(days=1))


async def test_options_api_and_create_api(client, login, api, vm_on, ctx):
    login(ctx.user)
    opts = (await client.get(api("/vms/options"))).json()
    assert opts["enabled"] and opts["name_prefix"] == "rent-" and opts["used_by_me"] == 0
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv", "expected_return_at": TOMORROW}
    r = await client.post(api("/vms"), json=body)
    assert r.status_code == 201 and r.json()["name"] == "rent-api-box" and r.json()["status"] == "queued"
    assert (await client.post(api("/vms"), json=body)).status_code == 409
    assert (await client.post(api("/vms"), json=body | {"name": "big", "cpu": 64})).status_code == 400


@pytest.mark.parametrize("patch", [{"requester_name": "     "}, {"requester_nick": "   "}], ids=["name", "nick"])
async def test_create_api_whitespace_only_requester_is_422(client, login, api, vm_on, ctx, patch):
    login(ctx.user)
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv", "expected_return_at": TOMORROW} | patch
    assert (await client.post(api("/vms"), json=body)).status_code == 422


@pytest.mark.parametrize("value", [None, "", "2020-01-01", "missing"], ids=["null", "empty", "past", "missing"])
async def test_create_api_return_date_is_required_422(client, login, api, vm_on, ctx, session, value):
    """Срок использования обязателен для ВМ, как и для ПК: без него, пустой или в прошлом — 422, заказ не создаётся."""
    login(ctx.user)
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv"}
    if value != "missing":
        body["expected_return_at"] = value
    assert (await client.post(api("/vms"), json=body)).status_code == 422
    assert await vms.list_vms(session) == []


async def test_create_api_saves_return_date(client, login, api, vm_on, ctx):
    login(ctx.user)
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv", "expected_return_at": TOMORROW}
    r = await client.post(api("/vms"), json=body)
    assert r.status_code == 201 and r.json()["expected_return_at"] == TOMORROW


# ---------- worker: создание ----------

async def test_create_next_success(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx, purpose="проверка")
    assert await vm_jobs.create_next(session) is True
    vm = await status_of(session, vm)
    assert (vm.status, vm.error, vm.vsphere_moid, vm.ip_address, vm.power_state) == (
        "ready", None, "vm-1", "10.0.0.5", "poweredOn")
    assert vm.ready_at is not None
    (name, cpu, ram, disk, annotation), = vsphere.created
    assert (name, cpu, ram, disk) == ("rent-dev-box", 4, 8, 100)
    assert "Иван Иванов" in annotation and "QA" in annotation and "проверка" in annotation
    notify.assert_awaited_once()
    assert "rent-dev-box" in notify.await_args.args[0]


async def test_create_next_empty_queue(session, vm_on, vsphere, notify):
    assert await vm_jobs.create_next(session) is False
    assert vsphere.created == []


async def test_create_failure_marks_failed_and_never_deletes_by_name(session, vm_on, ctx, vsphere, notify):
    vsphere.create_errors = [RuntimeError("datastore full")] * 2
    vm = await request(session, ctx)
    assert await vm_jobs.create_next(session) is True  # задача обработана, воркер не падает
    vm = await status_of(session, vm)
    assert vm.status == "failed" and "datastore full" in vm.error and vm.ready_at is None
    assert vsphere.deleted == []  # недоделанный клон убирает vSphere-клиент, а по имени воркер не удаляет ничего
    notify.assert_not_awaited()  # об успехе — уведомление, об ошибке — нет (см. xfail ниже)


async def test_create_failure_name_taken_by_foreign_vm_deletes_nothing(session, vm_on, ctx, vsphere, notify):
    """Имя уже занято чужой ВМ в vCenter: заявка падает, чужая ВМ остаётся нетронутой."""
    vsphere.create_errors = [VSphereError("ВМ с именем «rent-dev-box» уже есть в vCenter")] * 2
    vsphere.existing["rent-dev-box"] = VmInfo("vm-foreign", "rent-dev-box", "poweredOn", None)
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert vm.status == "failed" and "уже есть" in vm.error and vm.vsphere_moid is None
    assert vsphere.deleted == []


async def test_create_failure_retries_exactly_once(session, vm_on, ctx, vsphere, notify, pauses):
    """Две ошибки подряд: ровно две попытки, затем failed с текстом последней ошибки."""
    vsphere.create_errors = [RuntimeError("временный сбой"), RuntimeError("снова сбой")]
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert len(vsphere.created) == 2
    assert vm.status == "failed" and "снова сбой" in vm.error and vm.ready_at is None
    assert vsphere.deleted == []
    assert pauses == [10]  # пауза только перед повтором, после последней неудачи не ждём


async def test_create_retry_succeeds_after_one_failure(session, vm_on, ctx, vsphere, notify, pauses):
    vsphere.create_errors = [RuntimeError("временный сбой")]
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert len(vsphere.created) == 2
    assert vm.status == "ready" and vm.error is None and vm.vsphere_moid == "vm-2"
    assert vsphere.deleted == []
    assert pauses == [10]
    notify.assert_awaited_once()


async def test_create_no_retry_after_success(session, vm_on, ctx, vsphere, notify, pauses):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    assert len(vsphere.created) == 1 and vsphere.deleted == [] and pauses == []
    assert (await status_of(session, vm)).status == "ready"


@pytest.mark.xfail(strict=True, reason="При ошибке создания ВМ notify не вызывается (только при успехе)")
async def test_create_failure_notifies(session, vm_on, ctx, vsphere, notify):
    vsphere.create_errors = [RuntimeError("boom")] * 2  # обе попытки неудачны
    await request(session, ctx)
    await vm_jobs.create_next(session)
    notify.assert_awaited_once()


async def test_create_pending_drains_queue_one_by_one(session, vm_on, ctx, vsphere, notify):
    await runtime.update(session, {"vm_max_per_user": 5})
    for i in range(3):
        await request(session, ctx, name=f"vm-{i}")
    await vm_jobs.create_pending(session)
    assert len(vsphere.created) == 3
    rows = (await session.scalars(select(VirtualMachine).order_by(VirtualMachine.id)
                                  .execution_options(populate_existing=True))).unique().all()
    assert [v.status for v in rows] == ["ready"] * 3
    await vm_jobs.create_pending(session)  # пустая очередь — ничего не делает
    assert len(vsphere.created) == 3


async def test_create_pending_failed_vm_does_not_loop_forever(session, vm_on, ctx, vsphere, notify):
    await runtime.update(session, {"vm_max_per_user": 5})
    vsphere.create_errors = [RuntimeError("нет места")] * 2  # первая ВМ падает обеими попытками, вторая создаётся
    await request(session, ctx, name="vm-bad")
    await request(session, ctx, name="vm-ok")
    await vm_jobs.create_pending(session)
    rows = (await session.scalars(select(VirtualMachine).order_by(VirtualMachine.id)
                                  .execution_options(populate_existing=True))).unique().all()
    assert [v.status for v in rows] == ["failed", "ready"]


async def test_upkeep_deletes_at_most_batch_and_fills_ip(session, vm_on, ctx, vsphere, notify):
    await runtime.update(session, {"vm_max_per_user": 5})
    vsphere.ip = None
    made = [await request(session, ctx, name=f"vm-{i}") for i in range(3)]
    await vm_jobs.create_pending(session)
    for vm in made:
        await vms.release(session, ctx.user, vm.id)
    vsphere.ip = "10.1.1.1"
    await vm_jobs.upkeep(session, deletions=2)
    assert len(vsphere.deleted) == 2  # третья дождётся следующего круга
    await vm_jobs.upkeep(session, deletions=2)
    assert len(vsphere.deleted) == 3


# ---------- срок в Notes ВМ ----------

async def test_annotation_not_rewritten_when_term_unchanged(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert vm.notes_return_at == vm.expected_return_at  # при создании срок уже записан в Notes
    await vm_jobs.refresh_annotations(session)
    assert vsphere.annotations == []


async def test_extend_rewrites_annotation_once(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    first = vsphere.created[0][4]
    new_term = clock.today() + timedelta(days=60)
    await vms.extend(session, ctx.user, vm.id, extend_to(60))
    await vm_jobs.refresh_annotations(session)
    (moid, text), = vsphere.annotations
    assert moid == "vm-1" and f"Вернуть до: {new_term:%d.%m.%Y}" in text
    created_line = next(line for line in text.splitlines() if line.startswith("Создана:"))
    assert created_line in first  # время создания при обновлении не меняется
    assert (await status_of(session, vm)).notes_return_at == new_term
    await vm_jobs.refresh_annotations(session)  # повторно ничего не пишем
    assert len(vsphere.annotations) == 1


async def test_annotation_failure_is_retried_next_round(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    await vms.extend(session, ctx.user, vm.id, extend_to(60))
    vsphere.annotation_errors = [RuntimeError("vCenter недоступен")]
    await vm_jobs.refresh_annotations(session)  # ошибка не пробрасывается
    assert vsphere.annotations == [] and (await status_of(session, vm)).notes_return_at != clock.today() + timedelta(days=60)
    await vm_jobs.refresh_annotations(session)
    assert len(vsphere.annotations) == 1


async def test_annotation_skips_vms_that_are_not_ready_or_have_no_moid(session, vm_on, ctx, vsphere, notify):
    queued = await request(session, ctx)  # срок есть, а в Notes ничего не записано, но ВМ ещё нет в vCenter
    await vms.extend(session, ctx.user, queued.id, extend_to(60))
    await vm_jobs.refresh_annotations(session)
    assert vsphere.annotations == []


# ---------- данные подключения ----------

@pytest.mark.parametrize("os_value, method", [("windows", "RDP"), ("linux", "VNC"), (None, None)])
async def test_vm_connection_method_by_os(session, vm_on, ctx, os_value, method):
    vm = await request(session, ctx)
    vm.os = os_value
    await session.commit()
    out = VmOut.model_validate(await status_of(session, vm))
    assert (out.connection_login, out.connection_method) == ("user", method)


async def test_order_stores_template_os(session, vm_on, ctx):
    await runtime.update(session, {"vm_templates": [
        {"key": "ubuntu", "label": "Ubuntu 22.04", "os": "linux", "template": "T", "min_disk_gb": 20, "enabled": True}]})
    vm = await request(session, ctx, template_key="ubuntu", disk_gb=50)
    assert vm.os == "linux" and VmOut.model_validate(vm).connection_method == "VNC"


async def test_refresh_ips_fills_missing_ip(session, vm_on, ctx, vsphere, notify):
    vsphere.ip = None
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    assert (await status_of(session, vm)).ip_address is None
    vsphere.ip = "10.1.1.1"
    await vm_jobs.refresh_ips(session)
    assert (await status_of(session, vm)).ip_address == "10.1.1.1"


async def test_recover_creating(session, vm_on, ctx, vsphere):
    found, lost = await request(session, ctx, name="vm-found"), await request(session, ctx, name="vm-lost")
    for vm in (found, lost):
        vm.status = "creating"
    await session.commit()
    vsphere.existing["rent-vm-found"] = VmInfo("vm-77", "rent-vm-found", "poweredOn", None)
    await vm_jobs.recover(session)
    found, lost = await status_of(session, found), await status_of(session, lost)
    assert (found.status, found.vsphere_moid) == ("ready", "vm-77") and lost.status == "queued"


# ---------- удаление ----------

async def test_release_queued_is_immediate(session, vm_on, ctx):
    vm = await vms.release(session, ctx.user, (await request(session, ctx)).id)
    assert vm.status == "deleted" and vm.deleted_at and vm.released_by_id == ctx.user.id


async def test_release_failed_without_moid_is_immediate(session, vm_on, ctx, vsphere, notify):
    """Упавшая заявка в vCenter не создана: удалять нечего, и имя могла занять чужая ВМ — vSphere не трогаем."""
    vsphere.create_errors = [RuntimeError("нет места")] * 2
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await vms.release(session, ctx.user, vm.id)
    assert vm.status == "deleted" and vm.deleted_at
    assert await vm_jobs.delete_next(session) is False and vsphere.deleted == []


async def test_delete_next_without_moid_does_not_touch_vcenter(session, vm_on, ctx, vsphere):
    """Строки «deleting» без moid остались от прежней версии (failed -> deleting): закрываем без обращения к vCenter."""
    vm = await request(session, ctx)
    vm.status = "deleting"
    await session.commit()
    assert await vm_jobs.delete_next(session) is True
    assert (await status_of(session, vm)).status == "deleted" and vsphere.deleted == []


async def test_release_ready_goes_through_worker(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await vms.release(session, ctx.user, vm.id)
    assert vm.status == "deleting" and vsphere.deleted == []
    assert await vm_jobs.delete_next(session) is True
    vm = await status_of(session, vm)
    assert vm.status == "deleted" and vm.deleted_at and vm.error is None
    assert vsphere.deleted == ["vm-1"]
    assert await vm_jobs.delete_next(session) is False


async def test_delete_failure_retries_on_next_round(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    await vms.release(session, ctx.user, vm.id)
    vsphere.delete_errors = [RuntimeError("vCenter занят")]
    await vm_jobs.delete_next(session)
    vm = await status_of(session, vm)
    assert vm.status == "deleting" and "занят" in vm.error
    await vm_jobs.delete_next(session)
    vm = await status_of(session, vm)
    assert vm.status == "deleted" and vm.error is None


async def test_release_permissions_and_states(session, vm_on, ctx, make_user, vsphere, notify):
    stranger, admin = await make_user("petrov"), await make_user("boss", role="admin")
    vm = await request(session, ctx)
    with pytest.raises(Forbidden):
        await vms.release(session, stranger, vm.id)
    await vm_jobs.create_next(session)
    assert (await vms.release(session, admin, vm.id)).status == "deleting"  # админ может чужую
    with pytest.raises(Conflict, match="уже удаляется"):
        await vms.release(session, ctx.user, vm.id)

    creating = await request(session, ctx, name="vm-two")
    creating.status = "creating"
    await session.commit()
    with pytest.raises(Conflict, match="создаётся"):
        await vms.release(session, ctx.user, creating.id)


@pytest.mark.parametrize("team", ["other", "none"])
async def test_release_by_other_team_forbidden(session, vm_on, ctx, make_user, make_department, team):
    stranger = await make_user("petrov", department=await make_department("Ops") if team == "other" else None)
    vm = await request(session, ctx)
    with pytest.raises(Forbidden, match="участник его команды или администратор"):
        await vms.release(session, stranger, vm.id)
    assert (await status_of(session, vm)).status == "queued"


async def test_release_by_teammate(session, vm_on, ctx, make_user):
    """Участник команды отказывается от ВМ коллеги: заказ отменяется, в журнале — тот, кто отменил."""
    mate = await make_user("petrov", department=ctx.dept)
    vm = await request(session, ctx)
    vm = await vms.release(session, mate, vm.id)
    assert vm.status == "deleted" and vm.released_by_id == mate.id and vm.user_id == ctx.user.id


async def test_list_vms_mine_and_team(session, vm_on, ctx, make_user, make_department):
    mate = await make_user("petrov", department=ctx.dept)
    ops = await make_department("Ops")
    foreign = await make_user("sidorov", department=ops)
    loner = await make_user("loner")
    own = await request(session, ctx, name="own-box")
    by_mate = await vms.create_request(session, mate, payload(ctx.dept.id, name="mate-box"))
    by_loner = await vms.create_request(session, loner, payload(ctx.dept.id, name="loner-box"))  # на команду QA
    await vms.create_request(session, foreign, payload(ops.id, name="foreign-box"))

    assert [v.id for v in await vms.list_vms(session, ctx.user)] == [by_loner.id, by_mate.id, own.id]
    assert [v.id for v in await vms.list_vms(session, loner)] == [by_loner.id]  # без отдела — только свои
    assert len(await vms.list_vms(session)) == 4  # без пользователя — все (админка)


async def test_release_api_and_my_list(client, login, api, vm_on, ctx, session):
    vm = await request(session, ctx)
    login(ctx.user)
    mine = (await client.get(api("/vms/my"))).json()
    assert [v["id"] for v in mine] == [vm.id]
    r = await client.post(api(f"/vms/{vm.id}/release"))
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert (await client.post(api("/vms/9999/release"))).status_code == 404


# ---------- продление срока ----------

def extend_to(days: int, comment: str | None = None) -> VmExtend:
    return VmExtend(expected_return_at=clock.today() + timedelta(days=days), comment=comment)


async def extensions_of_vm(vm_id: int) -> list[BookingExtension]:
    async with SessionLocal() as s:
        q = select(BookingExtension).where(BookingExtension.vm_id == vm_id).order_by(BookingExtension.id)
        return list((await s.scalars(q)).unique().all())


async def test_extend_by_owner(session, vm_on, ctx):
    vm = await request(session, ctx)
    old, new = vm.expected_return_at, clock.today() + timedelta(days=40)
    vm = await vms.extend(session, ctx.user, vm.id, extend_to(40, "  ещё сборка  "))

    assert vm.expected_return_at == new and vm.status == "queued"
    [ext] = await extensions_of_vm(vm.id)
    assert (ext.booking_id, ext.user_id, ext.old_return_at, ext.new_return_at, ext.comment) == (
        None, ctx.user.id, old, new, "ещё сборка")
    assert ext.acknowledged_at is None and ext.acknowledged_by_id is None  # ждёт «Принято» админа


async def test_extend_by_teammate_logs_who_extended(session, vm_on, ctx, make_user):
    mate = await make_user("petrov", department=ctx.dept)
    vm = await vms.extend(session, mate, (await request(session, ctx)).id, extend_to(31))
    assert vm.user_id == ctx.user.id
    [ext] = await extensions_of_vm(vm.id)
    assert ext.user_id == mate.id and ext.acknowledged_at is None


async def test_extend_by_admin_is_already_acknowledged(session, vm_on, ctx, make_user):
    admin = await make_user("boss", role="admin")
    vm = await vms.extend(session, admin, (await request(session, ctx)).id, extend_to(31))
    [ext] = await extensions_of_vm(vm.id)
    assert ext.user_id == admin.id and ext.acknowledged_by_id == admin.id and ext.acknowledged_at is not None


@pytest.mark.parametrize("team", ["other", "none"])
async def test_extend_by_stranger_forbidden(session, vm_on, ctx, make_user, make_department, team):
    stranger = await make_user("petrov", department=await make_department("Ops") if team == "other" else None)
    vm = await request(session, ctx)
    with pytest.raises(Forbidden, match="Продлить ВМ может тот, кто её заказывал, участник его команды"):
        await vms.extend(session, stranger, vm.id, extend_to(31))
    assert await extensions_of_vm(vm.id) == []
    assert (await status_of(session, vm)).expected_return_at == clock.today() + timedelta(days=30)


@pytest.mark.parametrize("status", ["queued", "creating", "ready", "failed"])
async def test_extend_allowed_in_working_statuses(session, vm_on, ctx, status):
    vm = await request(session, ctx)
    vm.status = status
    await session.commit()
    assert (await vms.extend(session, ctx.user, vm.id, extend_to(31))).status == status


@pytest.mark.parametrize("status", ["deleting", "deleted"])
async def test_extend_deleted_or_deleting_conflict(session, vm_on, ctx, status):
    vm = await request(session, ctx)
    vm.status = status
    await session.commit()
    with pytest.raises(Conflict, match="удаляется или уже удалена"):
        await vms.extend(session, ctx.user, vm.id, extend_to(31))
    assert await extensions_of_vm(vm.id) == []


@pytest.mark.parametrize("days", [30, 29, 0])
async def test_extend_not_later_than_current_conflict(session, vm_on, ctx, days):
    vm = await request(session, ctx)  # срок: сегодня + 30
    with pytest.raises(Conflict, match="позже текущего"):
        await vms.extend(session, ctx.user, vm.id, extend_to(days))
    assert await extensions_of_vm(vm.id) == []
    assert (await status_of(session, vm)).expected_return_at == clock.today() + timedelta(days=30)


async def test_extend_vm_without_date(session, vm_on, ctx):
    """У ВМ, созданных до обязательного срока, даты нет: продлить можно на любую с сегодняшней."""
    vm = await request(session, ctx)
    vm.expected_return_at = None
    await session.commit()
    vm = await vms.extend(session, ctx.user, vm.id, extend_to(0))
    assert vm.expected_return_at == clock.today()
    [ext] = await extensions_of_vm(vm.id)
    assert ext.old_return_at is None


@pytest.mark.parametrize("comment", [None, "", "   "])
async def test_extend_empty_comment_becomes_none(session, vm_on, ctx, comment):
    vm = await vms.extend(session, ctx.user, (await request(session, ctx)).id, extend_to(31, comment))
    [ext] = await extensions_of_vm(vm.id)
    assert ext.comment is None


async def test_extend_missing_not_found(session, vm_on, ctx):
    with pytest.raises(NotFound, match="Виртуалка не найдена"):
        await vms.extend(session, ctx.user, 9999, extend_to(31))


async def test_extend_waits_for_worker_that_took_the_vm(session, vm_on, ctx):
    """Продление берёт ту же блокировку строки, что и worker: не пишет срок поверх взятой в работу ВМ."""
    vm = await request(session, ctx)
    async with SessionLocal() as worker:
        assert (await vm_jobs._take(worker, "queued")).id == vm.id
        async with SessionLocal() as other:
            extending = asyncio.create_task(vms.extend(other, ctx.user, vm.id, extend_to(31)))
            await asyncio.sleep(0.3)
            assert not extending.done()
            await worker.commit()
            assert (await extending).expected_return_at == clock.today() + timedelta(days=31)


async def test_extend_api(client, login, api, vm_on, ctx, session, make_user, make_department):
    vm = await request(session, ctx)
    new = (clock.today() + timedelta(days=45)).isoformat()
    url = api(f"/vms/{vm.id}/extend")

    login(await make_user("outsider", department=await make_department("Ops")))
    assert (await client.post(url, json={"expected_return_at": new})).status_code == 403

    login(await make_user("mate", department=ctx.dept))
    r = await client.post(url, json={"expected_return_at": new, "comment": "ещё сборка"})
    assert r.status_code == 200, r.text
    assert (r.json()["id"], r.json()["expected_return_at"], r.json()["status"]) == (vm.id, new, "queued")

    assert (await client.post(url, json={"expected_return_at": new})).status_code == 409  # не позже текущего
    assert (await client.post(api("/vms/9999/extend"), json={"expected_return_at": new})).status_code == 404


@pytest.mark.parametrize("body", [
    {}, {"expected_return_at": None}, {"expected_return_at": "2020-01-01"}, {"expected_return_at": "не дата"},
    {"expected_return_at": TOMORROW, "comment": "x" * 2001},
], ids=["missing", "null", "past", "garbage", "long-comment"])
async def test_extend_api_validation_422(client, login, api, vm_on, ctx, session, body):
    vm = await request(session, ctx)
    login(ctx.user)
    assert (await client.post(api(f"/vms/{vm.id}/extend"), json=body)).status_code == 422
    assert await extensions_of_vm(vm.id) == []


# ---------- гонки ----------

async def test_release_waits_for_worker_that_took_the_vm(session, vm_on, ctx):
    """Worker уже взял ВМ из очереди (строка заблокирована): отказ дожидается его и видит «creating», а не «queued»."""
    vm = await request(session, ctx)
    async with SessionLocal() as worker:
        taken = await vm_jobs._take(worker, "queued")
        assert taken.id == vm.id
        async with SessionLocal() as other:
            releasing = asyncio.create_task(vms.release(other, ctx.user, vm.id))
            await asyncio.sleep(0.3)
            assert not releasing.done()  # без FOR UPDATE отказ прочитал бы «queued» и сразу пометил ВМ удалённой
            taken.status = "creating"
            await worker.commit()
            with pytest.raises(Conflict, match="создаётся"):
                await releasing
    assert (await status_of(session, vm)).status == "creating"


async def _create_in_own_session(user, dept_id, name):
    async with SessionLocal() as s:
        return await vms.create_request(s, user, payload(dept_id, name=name))


@pytest.mark.parametrize("limit", [1, 2])
async def test_per_user_limit_holds_under_concurrent_requests(session, vm_on, ctx, limit):
    """Пять одновременных заявок одного человека: проходит ровно limit, остальные — отказ по лимиту."""
    await runtime.update(session, {"vm_max_per_user": limit})
    results = await asyncio.gather(
        *(_create_in_own_session(ctx.user, ctx.dept.id, f"vm-race{i}") for i in range(5)), return_exceptions=True)
    created = [r for r in results if isinstance(r, VirtualMachine)]
    refused = [r for r in results if not isinstance(r, VirtualMachine)]
    assert len(created) == limit
    assert all(isinstance(e, Conflict) and "доступных виртуалок" in str(e) for e in refused), refused
    assert await vms._alive_count(session, ctx.user.id) == limit


async def test_limit_lock_does_not_block_other_users(session, vm_on, ctx, make_user):
    await runtime.update(session, {"vm_max_per_user": 1})
    other = await make_user("petrov", department=ctx.dept)
    results = await asyncio.gather(
        _create_in_own_session(ctx.user, ctx.dept.id, "vm-first"), _create_in_own_session(other, ctx.dept.id, "vm-second"))
    assert all(isinstance(r, VirtualMachine) for r in results)


async def test_my_vms_api_includes_team(client, login, api, vm_on, ctx, session, make_user, make_department):
    vm = await request(session, ctx)
    login(await make_user("outsider", department=await make_department("Ops")))
    assert (await client.get(api("/vms/my"))).json() == []
    assert (await client.post(api(f"/vms/{vm.id}/release"))).status_code == 403
    login(await make_user("mate", department=ctx.dept))
    assert [v["id"] for v in (await client.get(api("/vms/my"))).json()] == [vm.id]
    assert (await client.post(api(f"/vms/{vm.id}/release"))).status_code == 200
