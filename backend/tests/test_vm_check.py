"""Проверка ВМ исполнителем (DR-15072): статус checking, подтверждение, пересоздание, отклонение, задача в Jira.

vSphere и Mattermost — фейки из test_vm_jobs, Jira — FakeSd из test_service_requests.
"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.db.session import SessionLocal
from app.integrations import servicedesk as real_sd
from app.integrations.vsphere.client import VmInfo
from app.models import NotificationKind, ServiceRequest, UserRole, VirtualMachine, VmStatus
from app.services import executor, jira_closure, runtime, service_requests, vm_jobs, vms

from .test_service_requests import boom, sd  # noqa: F401 — sd: Service Desk подключён, клиент Jira подменён
from .test_vm_jobs import ctx, notes, notify, pauses, payload, request, status_of, vm_on, vsphere  # noqa: F401


@pytest.fixture(autouse=True)
def check_on(monkeypatch, vm_on, vsphere, notify, sd):  # noqa: F811
    """Проверка включена; закрытие в Jira читает ту же подмену клиента."""
    monkeypatch.setattr(settings, "vm_executor_check", True)
    monkeypatch.setattr(jira_closure, "sd", service_requests.sd)
    monkeypatch.setattr(executor, "notify", notify)


async def _tasks() -> list[ServiceRequest]:
    async with SessionLocal() as s:
        return list((await s.scalars(select(ServiceRequest).order_by(ServiceRequest.id))).unique().all())


async def _created(session, ctx) -> VirtualMachine:  # noqa: F811
    vm = await request(session, ctx)
    assert await vm_jobs.create_next(session)
    return await status_of(session, vm)


# ---------- создание ----------

async def test_created_vm_waits_for_executor_and_task_is_opened(session, ctx, notify, sd):  # noqa: F811
    vm = await _created(session, ctx)
    assert vm.status == VmStatus.checking and vm.ready_at is None and vm.checked_at is None
    assert vm.vsphere_moid and vm.ip_address == "10.0.0.5"  # исполнителю есть что проверять
    assert not [n for n in await notes() if n.kind == NotificationKind.vm_ready]  # заказчику ещё ничего не готово
    assert "ждёт проверки исполнителем" in notify.await_args.args[0]
    (task,) = await _tasks()
    assert (task.kind, task.vm_id, task.booking_id, task.issue_key) == ("prepare", vm.id, None, "HMS-1")
    assert f"подготовить ВМ {vm.name} (заказ №{vm.order_number})" in sd.created[0][1]
    assert "/executor" in sd.created[0][2] and "Арендатор: Иван Иванов" in sd.created[0][2]


async def test_without_check_vm_is_ready_at_once(session, ctx, monkeypatch, sd):  # noqa: F811
    monkeypatch.setattr(settings, "vm_executor_check", False)
    vm = await _created(session, ctx)
    assert vm.status == VmStatus.ready and vm.ready_at is not None
    assert [n.kind for n in await notes()] == [NotificationKind.vm_ready] and await _tasks() == []


async def test_jira_failure_does_not_break_creation(session, ctx, sd):  # noqa: F811
    sd.create_error = boom()
    vm = await _created(session, ctx)
    assert vm.status == VmStatus.checking
    (task,) = await _tasks()
    assert task.issue_key is None and task.error  # ошибка сохранена в заявке


async def test_cluster_shortage_fails_vm_and_opens_task_with_note(session, ctx, vsphere, sd):  # noqa: F811
    vsphere.free_ram_gb = 1
    vm = await _created(session, ctx)
    assert vm.status == VmStatus.failed and "мощностей" in vm.error
    (task,) = await _tasks()
    assert "ВМ не создана" in sd.created[0][2] and "мощностей" in sd.created[0][2]
    # портал закроет такую задачу как Rejected: ВМ не создаётся
    await _round(session, sd, "Backlog")
    assert sd.closed == [(task.issue_key, "Rejected")]


async def test_recover_puts_started_vm_on_check(session, ctx, vsphere):  # noqa: F811
    vm = await request(session, ctx)
    vm.status = VmStatus.creating.value
    await session.commit()
    vsphere.existing[vm.name] = VmInfo(moid="vm-9", name=vm.name, power_state="poweredOn", ip_address="10.0.0.9")
    await vm_jobs.recover(session)
    assert (await status_of(session, vm)).status == VmStatus.checking


async def test_ip_is_picked_up_while_vm_is_on_check(session, ctx, vsphere):  # noqa: F811
    vsphere.ip = None
    vm = await _created(session, ctx)
    assert vm.ip_address is None
    vsphere.ip = "10.0.0.7"
    await vm_jobs.refresh_ips(session)
    assert (await status_of(session, vm)).ip_address == "10.0.0.7"


# ---------- подтверждение ----------

async def test_confirm_makes_vm_ready_and_tells_customer(session, ctx, make_user, notify):  # noqa: F811
    vm = await _created(session, ctx)
    worker = await make_user("worker", role=UserRole.executor.value)
    out = await executor.confirm_vm(session, worker, vm.id)
    assert out.status == VmStatus.ready and out.ready_at is not None and out.checked_at is not None
    assert out.checked_by_id == worker.id and out.insight_pending is True
    (note,) = [n for n in await notes() if n.kind == NotificationKind.vm_ready]
    assert note.user_id == ctx.user.id
    assert "проверена исполнителем" in notify.await_args.args[0]


@pytest.mark.parametrize("state", ["ready", "queued", "deleting", "failed"])
async def test_only_vm_on_check_can_be_decided(session, ctx, state):  # noqa: F811
    vm = await _created(session, ctx)
    vm.status = state
    await session.commit()
    for call in (lambda: executor.confirm_vm(session, None, vm.id), lambda: executor.recreate_vm(session, vm.id),
                 lambda: executor.reject_vm(session, None, vm.id, "Некорректный заказ", "дубль")):
        with pytest.raises(Conflict, match="ВМ уже не на проверке"):
            await call()


async def test_unknown_vm_is_not_found(session):
    with pytest.raises(NotFound):
        await executor.confirm_vm(session, None, 999)


# ---------- пересоздать ----------

async def test_recreate_deletes_vm_and_creates_it_again_with_same_name(session, ctx, vsphere, sd):  # noqa: F811
    vm = await _created(session, ctx)
    name, number = vm.name, vm.insight_object_id
    await executor.recreate_vm(session, vm.id)
    assert (await status_of(session, vm)).status == VmStatus.deleting
    await vm_jobs.delete_next(session)
    back = await status_of(session, vm)
    assert (back.status, back.recreate, back.vsphere_moid, back.deleted_at) == (VmStatus.queued, False, None, None)
    assert vsphere.deleted == ["vm-1"] and (back.name, back.insight_object_id) == (name, number)  # номер сохранён

    assert await vm_jobs.create_next(session)
    again = await status_of(session, vm)
    assert again.status == VmStatus.checking and again.vsphere_moid == "vm-2"
    assert len(await _tasks()) == 1  # одна задача на ВМ: повторно её не открывают


async def test_recreating_vm_task_stays_open(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    await executor.recreate_vm(session, vm.id)
    sd.status = real_sd.SdStatus("In Progress", "indeterminate")
    await service_requests.refresh_open(session)
    assert sd.closed == []  # пересоздаваемая ВМ — не отклонённая


# ---------- отклонение ----------

async def test_reject_removes_vm_frees_number_and_explains_to_customer(session, ctx, make_user, vsphere):  # noqa: F811
    vm = await _created(session, ctx)
    worker = await make_user("worker", role=UserRole.executor.value)
    out = await executor.reject_vm(session, worker, vm.id, "Не удалось подготовить ВМ", "Не стартует")
    assert out.status == VmStatus.deleting and out.released_by_id is None and out.checked_by_id == worker.id
    (note,) = [n for n in await notes() if n.kind == NotificationKind.order_rejected]
    assert note.user_id == ctx.user.id and "Не удалось подготовить ВМ" in note.title and "Не стартует" in note.body
    await vm_jobs.delete_next(session)
    gone = await status_of(session, vm)
    assert gone.status == VmStatus.deleted and gone.insight_pending is True and vsphere.deleted == ["vm-1"]


# ---------- закрытие задач ----------

async def _round(session, sd, status):  # noqa: F811
    """Круг worker'а: статус задачи в Jira и закрытие порталом."""
    sd.status = real_sd.SdStatus(status, "new")
    async with SessionLocal() as s:
        for t in (await s.scalars(select(ServiceRequest))).unique():
            t.last_checked_at = None
        await s.commit()
    await service_requests.refresh_open(session)


async def test_portal_closes_task_done_after_confirm(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    await _round(session, sd, "In Progress")
    assert sd.closed == []  # проверка ещё идёт
    await executor.confirm_vm(session, None, vm.id)
    await _round(session, sd, "In Progress")
    assert sd.closed == [("HMS-1", "Done")]


async def test_portal_closes_task_rejected_after_reject_and_after_customer_delete(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    await executor.reject_vm(session, None, vm.id, "Некорректный заказ", "дубль")
    await _round(session, sd, "Backlog")
    assert sd.closed == [("HMS-1", "Rejected")]


# ---------- закрыли задачу в Jira ----------

async def _closed_in_jira(session, ctx, resolution, closer=None):  # noqa: F811
    vm = await _created(session, ctx)
    (task,) = await _tasks()
    async with SessionLocal() as s:
        t = await s.get(ServiceRequest, task.id)
        t.status, t.status_category = "Done", "done"
        await s.commit()
    sd_ = service_requests.sd
    sd_.details = real_sd.SdDetails(taken=True, resolution=resolution, closed_by=closer)
    sd_.comments = [real_sd.SdComment("Олег", "Диск битый", None, False)]
    await jira_closure.apply_closures(session)
    return vm


async def test_closed_done_in_jira_confirms_vm(session, ctx, make_user, sd):  # noqa: F811
    await make_user("oleg", role=UserRole.executor.value)
    vm = await _closed_in_jira(session, ctx, "Done", ("oleg", ""))
    out = await status_of(session, vm)
    assert out.status == VmStatus.ready and out.checked_by_id is not None
    assert (await _tasks())[0].handled_at is not None


async def test_closed_rejected_in_jira_rejects_vm_with_comment(session, ctx, sd):  # noqa: F811
    vm = await _closed_in_jira(session, ctx, "Rejected")
    assert (await status_of(session, vm)).status == VmStatus.deleting
    (note,) = [n for n in await notes() if n.kind == NotificationKind.order_rejected]
    assert "Закрыто в Jira" in note.title and "Диск битый" in note.body


async def test_closed_in_jira_after_portal_decision_changes_nothing(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    await executor.confirm_vm(session, None, vm.id)
    (task,) = await _tasks()
    async with SessionLocal() as s:
        t = await s.get(ServiceRequest, task.id)
        t.status, t.status_category = "Done", "done"
        await s.commit()
    sd.details = real_sd.SdDetails(taken=True, resolution="Rejected")
    await jira_closure.apply_closures(session)
    assert (await status_of(session, vm)).status == VmStatus.ready  # решение уже принято в портале
    assert (await _tasks())[0].handled_at is not None


# ---------- отказ заказчика во время проверки ----------

async def test_customer_can_delete_vm_on_check_while_task_is_in_backlog(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    sd.status = real_sd.SdStatus("Backlog", "new")
    out = await vms.release(session, ctx.user, vm.id)
    assert out.status == VmStatus.deleting and sd.status_calls == ["HMS-1"]


async def test_customer_cannot_delete_vm_the_executor_already_took(session, ctx, sd):  # noqa: F811
    vm = await _created(session, ctx)
    sd.status = real_sd.SdStatus("In Progress", "indeterminate")
    with pytest.raises(Conflict, match="Исполнитель уже взял заказ в работу"):
        await vms.release(session, ctx.user, vm.id)
    assert (await status_of(session, vm)).status == VmStatus.checking


async def test_admin_can_always_delete_vm_on_check(session, ctx, make_user, sd):  # noqa: F811
    vm = await _created(session, ctx)
    sd.status = real_sd.SdStatus("In Progress", "indeterminate")
    admin = await make_user("boss", role=UserRole.admin.value)
    assert (await vms.release(session, admin, vm.id)).status == VmStatus.deleting
    assert sd.status_calls == []


async def test_stranger_is_denied_before_jira_is_asked(session, ctx, make_user, sd):  # noqa: F811
    from app.core.errors import Forbidden
    vm = await _created(session, ctx)
    with pytest.raises(Forbidden):
        await vms.release(session, await make_user("stranger"), vm.id)
    assert sd.status_calls == []


async def test_vm_on_check_counts_in_users_limit(session, ctx, make_user):  # noqa: F811
    await _created(session, ctx)
    assert (await vms.options(session, ctx.user)).used_by_me == 1


# ---------- API исполнителя ----------

@pytest.fixture
async def worker(make_user, login):
    user = await make_user("worker", role=UserRole.executor.value, display_name="Пётр Исполнитель")
    login(user)
    return user


async def test_api_lists_vms_on_check_with_jira_link(client, api, worker, session, ctx, sd, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "sd_jira_url", "https://jira.test")
    vm = await _created(session, ctx)
    other = await request(session, ctx)  # ещё в очереди: исполнителю не показывается
    rows = (await client.get(api("/executor/vms"))).json()
    assert [r["id"] for r in rows] == [vm.id] and other.id != vm.id
    row = rows[0]
    assert (row["name"], row["status"], row["ip_address"], row["os_label"]) == (vm.name, "checking", "10.0.0.5", vm.os_label)
    assert (row["request_key"], row["request_url"]) == ("HMS-1", "https://jira.test/browse/HMS-1")
    assert (row["user"]["username"], row["department"]["name"]) == ("ivanov", "QA")


async def test_api_confirm_recreate_reject(client, api, worker, session, ctx, sd):  # noqa: F811
    await runtime.update(session, {"vm_max_per_user": 5})
    first, second, third = [await _created(session, ctx) for _ in range(3)]
    assert (await client.post(api(f"/executor/vms/{first.id}/confirm"))).json()["status"] == "ready"
    assert (await client.post(api(f"/executor/vms/{second.id}/recreate"))).json()["status"] == "deleting"
    r = await client.post(api(f"/executor/vms/{third.id}/reject"),
                          json={"reason": "Недостаточно мощностей кластера", "comment": "Нет памяти"})
    assert r.status_code == 200 and r.json()["status"] == "deleting"
    assert (await client.get(api("/executor/vms"))).json() == []
    for path in ("confirm", "recreate"):  # повторное решение — 409
        assert (await client.post(api(f"/executor/vms/{first.id}/{path}"))).status_code == 409
    assert (await client.post(api("/executor/vms/9999/confirm"))).status_code == 404


@pytest.mark.parametrize("body", [
    {}, {"reason": "Некорректный заказ"}, {"reason": "Некорректный заказ", "comment": "  "},
    {"reason": "Не нравится", "comment": "x"}, {"reason": "Некорректный заказ", "comment": "x" * 2001},
], ids=["empty", "no_comment", "spaces", "unknown_reason", "too_long"])
async def test_api_reject_validation_422(client, api, worker, session, ctx, body):  # noqa: F811
    vm = await _created(session, ctx)
    assert (await client.post(api(f"/executor/vms/{vm.id}/reject"), json=body)).status_code == 422


async def test_api_customer_cannot_decide(client, api, session, ctx, login):  # noqa: F811
    vm = await _created(session, ctx)
    login(ctx.user)
    assert (await client.get(api("/executor/vms"))).status_code == 403
    assert (await client.post(api(f"/executor/vms/{vm.id}/confirm"))).status_code == 403
