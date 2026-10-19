"""Виртуалки: заявка (services/vms.py) и фоновые задачи (services/vm_jobs.py). vSphere и Mattermost — фейки."""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import Conflict, DomainError, Forbidden
from app.integrations.vsphere.client import VmInfo
from app.models import VirtualMachine
from app.schemas.vm import VmCreate
from app.services import runtime, vm_jobs, vms


class FakeVSphere:
    """Замена модуля app.integrations.vsphere.client целиком: без pyVmomi и сети."""

    def __init__(self):
        self.create_errors: list[Exception | None] = []  # по одному на вызов create_vm; None — успех
        self.delete_errors: list[Exception | None] = []
        self.created: list[tuple] = []
        self.deleted: list[tuple] = []
        self.existing: dict[str, VmInfo] = {}
        self.ip: str | None = "10.0.0.5"

    def create_vm(self, name, cpu, ram_gb, disk_gb, annotation, template_name=None, customization_spec=None):
        self.created.append((name, cpu, ram_gb, disk_gb, annotation))
        if self.create_errors and (err := self.create_errors.pop(0)):
            raise err
        return VmInfo(moid=f"vm-{len(self.created)}", name=name, power_state="poweredOn", ip_address=self.ip)

    def delete_vm(self, moid, name):
        self.deleted.append((moid, name))
        if self.delete_errors and (err := self.delete_errors.pop(0)):
            raise err

    def vm_status(self, moid):
        return VmInfo(moid=moid, name="x", power_state="poweredOn", ip_address=self.ip)

    def find_vm(self, name):
        return self.existing.get(name)


@pytest.fixture
def vsphere(monkeypatch):
    fake = FakeVSphere()
    for mod in (vm_jobs, vms):
        monkeypatch.setattr(mod, "vsphere", fake)
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
    for mod in (vm_jobs, vms):
        monkeypatch.setattr(mod, "notify", mock)
    return mock


@pytest.fixture
async def vm_on(session, monkeypatch):
    """vCenter «настроен» и конструктор включён."""
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)
    await runtime.update(session, {"vm_enabled": True})


def payload(dept_id: int, **kw) -> VmCreate:
    data = {"name": "Dev-Box", "cpu": 4, "ram_gb": 8, "disk_gb": 100, "department_id": dept_id,
            "requester_name": "Иван Иванов", "requester_nick": "ivan", "purpose": "тесты"}
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
        payload(1, expected_return_at=date.today() - timedelta(days=1))


async def test_options_api_and_create_api(client, login, api, vm_on, ctx):
    login(ctx.user)
    opts = (await client.get(api("/vms/options"))).json()
    assert opts["enabled"] and opts["name_prefix"] == "rent-" and opts["used_by_me"] == 0
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv"}
    r = await client.post(api("/vms"), json=body)
    assert r.status_code == 201 and r.json()["name"] == "rent-api-box" and r.json()["status"] == "queued"
    assert (await client.post(api("/vms"), json=body)).status_code == 409
    assert (await client.post(api("/vms"), json=body | {"name": "big", "cpu": 64})).status_code == 400


@pytest.mark.parametrize("patch", [{"requester_name": "     "}, {"requester_nick": "   "}], ids=["name", "nick"])
async def test_create_api_whitespace_only_requester_is_422(client, login, api, vm_on, ctx, patch):
    login(ctx.user)
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv"} | patch
    assert (await client.post(api("/vms"), json=body)).status_code == 422


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


async def test_create_failure_marks_failed_and_cleans_up(session, vm_on, ctx, vsphere, notify):
    vsphere.create_errors = [RuntimeError("datastore full")] * 2
    vm = await request(session, ctx)
    assert await vm_jobs.create_next(session) is True  # задача обработана, воркер не падает
    vm = await status_of(session, vm)
    assert vm.status == "failed" and "datastore full" in vm.error and vm.ready_at is None
    assert vsphere.deleted == [(None, "rent-dev-box")] * 2  # недоделанный клон убран по имени после каждой попытки
    notify.assert_not_awaited()  # об успехе — уведомление, об ошибке — нет (см. xfail ниже)


async def test_cleanup_error_is_swallowed(session, vm_on, ctx, vsphere, notify):
    vsphere.create_errors = [RuntimeError("clone failed")] * 2
    vsphere.delete_errors = [RuntimeError("vCenter недоступен")] * 2
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    assert (await status_of(session, vm)).status == "failed"


async def test_create_failure_retries_exactly_once(session, vm_on, ctx, vsphere, notify, pauses):
    """Две ошибки подряд: ровно две попытки, затем failed с текстом последней ошибки."""
    vsphere.create_errors = [RuntimeError("временный сбой"), RuntimeError("снова сбой")]
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert len(vsphere.created) == 2
    assert vm.status == "failed" and "снова сбой" in vm.error and vm.ready_at is None
    assert vsphere.deleted == [(None, "rent-dev-box")] * 2  # после каждой неудачи клон убирается
    assert pauses == [10]  # пауза только перед повтором, после последней неудачи не ждём


async def test_create_retry_succeeds_after_one_failure(session, vm_on, ctx, vsphere, notify, pauses):
    vsphere.create_errors = [RuntimeError("временный сбой")]
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await status_of(session, vm)
    assert len(vsphere.created) == 2
    assert vm.status == "ready" and vm.error is None and vm.vsphere_moid == "vm-2"
    assert vsphere.deleted == [(None, "rent-dev-box")]  # перед повтором убран недоделанный клон
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


async def test_run_once_noop_without_vcenter(session, ctx, vsphere, notify):
    session.add(VirtualMachine(name="rent-x", cpu=2, ram_gb=4, disk_gb=50, status="queued", order_number=1,
                               user_id=ctx.user.id, department_id=ctx.dept.id, requester_name="a",
                               requester_nick="b", attrs={}))
    await session.commit()
    await vm_jobs.run_once(session)  # vcenter_host пуст
    assert vsphere.created == []


async def test_run_once_creates_at_most_two(session, vm_on, ctx, vsphere, notify):
    await runtime.update(session, {"vm_max_per_user": 5})
    for i in range(3):
        await request(session, ctx, name=f"vm-{i}")
    await vm_jobs.run_once(session)
    assert len(vsphere.created) == 2
    rows = (await session.scalars(select(VirtualMachine).order_by(VirtualMachine.id)
                                  .execution_options(populate_existing=True))).unique().all()
    assert [v.status for v in rows] == ["ready", "ready", "queued"]


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


async def test_release_ready_goes_through_worker(session, vm_on, ctx, vsphere, notify):
    vm = await request(session, ctx)
    await vm_jobs.create_next(session)
    vm = await vms.release(session, ctx.user, vm.id)
    assert vm.status == "deleting" and vsphere.deleted == []
    assert await vm_jobs.delete_next(session) is True
    vm = await status_of(session, vm)
    assert vm.status == "deleted" and vm.deleted_at and vm.error is None
    assert vsphere.deleted == [("vm-1", "rent-dev-box")]
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


async def test_release_api_and_my_list(client, login, api, vm_on, ctx, session):
    vm = await request(session, ctx)
    login(ctx.user)
    mine = (await client.get(api("/vms/my"))).json()
    assert [v["id"] for v in mine] == [vm.id]
    r = await client.post(api(f"/vms/{vm.id}/release"))
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert (await client.post(api("/vms/9999/release"))).status_code == 404
