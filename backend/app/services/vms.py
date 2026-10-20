"""Виртуалки из конструктора: заявка → очередь → worker клонирует шаблон в vSphere → «Моя аренда»."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Conflict, DomainError, NotFound
from app.db.integrity import conflict_on_integrity_error
from app.integrations.vsphere import client as vsphere
from app.models import User, VirtualMachine, VmStatus
from app.schemas.settings import RuntimeConfig, VmTemplate
from app.schemas.vm import VmCreate, VmExtend, VmOptions, VmTemplateOption
from app.services import departments, overdue, runtime
from app.services.access import ensure_access, mine_or_team
from app.services.orders import next_order_number

ALIVE = (VmStatus.queued, VmStatus.creating, VmStatus.ready, VmStatus.deleting)
VM_LIMIT_LOCK_KEY = 73010002  # пространство ключей advisory-lock для лимита ВМ на пользователя (свой ключ у sync.py)


async def _alive_count(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(
        select(func.count()).where(VirtualMachine.user_id == user_id, VirtualMachine.status.in_(ALIVE))
    ) or 0


def _available_templates(cfg: RuntimeConfig) -> list[VmTemplate]:
    """Шаблоны, из которых можно создавать: включены и указано имя шаблона в vCenter."""
    return [t for t in cfg.vm_templates if t.enabled and t.template]


async def options(session: AsyncSession, user: User) -> VmOptions:
    cfg = await runtime.load(session)
    used = await _alive_count(session, user.id)
    reason = None
    if not settings.vsphere_configured:
        reason = "Конструктор не подключён к vCenter"
    elif not cfg.vm_enabled:
        reason = "Конструктор временно выключен администратором"
    elif not _available_templates(cfg):
        reason = "Нет настроенных шаблонов ОС — админ добавляет их в «Настройках»"
    elif used >= cfg.vm_max_per_user:
        reason = f"У вас уже {used} из {cfg.vm_max_per_user} доступных виртуалок"
    return VmOptions(
        enabled=reason is None, reason=reason, name_prefix=settings.vm_name_prefix,
        template=next((t.label for t in _available_templates(cfg)), "—"),
        min_cpu=cfg.vm_min_cpu, max_cpu=cfg.vm_max_cpu, min_ram_gb=cfg.vm_min_ram_gb, max_ram_gb=cfg.vm_max_ram_gb,
        min_disk_gb=cfg.vm_min_disk_gb, max_disk_gb=cfg.vm_max_disk_gb,
        max_per_user=cfg.vm_max_per_user, used_by_me=used,
        templates=[
            VmTemplateOption(key=t.key, label=t.label, os=t.os, min_disk_gb=max(t.min_disk_gb, cfg.vm_min_disk_gb),
                             available=bool(t.enabled and t.template))
            for t in cfg.vm_templates if t.enabled  # включён, но без шаблона — в конструкторе «скоро»
        ],
    )


async def check_vcenter() -> dict:
    """Проверка подключения к vCenter и наличия включённых шаблонов (кнопка в «Настройках»)."""
    try:
        names = [t.template for t in _available_templates(runtime.current())]
        return {"ok": True, **(await asyncio.to_thread(vsphere.check, names))}
    except vsphere.VSphereError as exc:
        return {"ok": False, "error": str(exc)}


async def create_request(session: AsyncSession, user: User, data: VmCreate) -> VirtualMachine:
    # Лимит «ВМ на человека» считается по строкам, которых ещё нет: без блокировки два параллельных запроса
    # оба увидят «мест хватает». Lock снимается сам при commit/rollback, запросы других пользователей не ждут.
    await session.execute(select(func.pg_advisory_xact_lock(VM_LIMIT_LOCK_KEY, user.id)))
    opts = await options(session, user)
    if not opts.enabled:
        raise Conflict(opts.reason or "Конструктор недоступен")
    for value, lo, hi, what in (
        (data.cpu, opts.min_cpu, opts.max_cpu, "ядер"),
        (data.ram_gb, opts.min_ram_gb, opts.max_ram_gb, "ГБ памяти"),
        (data.disk_gb, opts.min_disk_gb, opts.max_disk_gb, "ГБ диска"),
    ):
        if not lo <= value <= hi:
            raise DomainError(f"Допустимо от {lo} до {hi} {what}")
    templates = {t.key: t for t in _available_templates(runtime.current())}
    tmpl = templates.get(data.template_key) if data.template_key else next(iter(templates.values()), None)
    if tmpl is None:
        raise DomainError("Эта ОС пока недоступна — выберите другую")
    if data.disk_gb < tmpl.min_disk_gb:
        raise DomainError(f"Для {tmpl.label} диск — не меньше {tmpl.min_disk_gb} ГБ")
    dept = await departments.get_active(session, data.department_id)
    vm = VirtualMachine(
        order_number=await next_order_number(session),
        name=f"{settings.vm_name_prefix}{data.name}", cpu=data.cpu, ram_gb=data.ram_gb, disk_gb=data.disk_gb,
        status=VmStatus.queued.value, user_id=user.id, department_id=dept.id, template_key=tmpl.key, os_label=tmpl.label,
        requester_name=data.requester_name, requester_nick=data.requester_nick,
        purpose=data.purpose or None, expected_return_at=data.expected_return_at, attrs={},
    )
    session.add(vm)
    async with conflict_on_integrity_error(session, f"Имя «{vm.name}» уже занято — придумайте другое"):
        await session.commit()
    return await get_vm(session, vm.id)


async def get_vm(session: AsyncSession, vm_id: int) -> VirtualMachine:
    vm = await session.scalar(
        select(VirtualMachine).where(VirtualMachine.id == vm_id).execution_options(populate_existing=True)
    )
    if vm is None:
        raise NotFound("Виртуалка не найдена")
    return vm


async def _lock_vm(session: AsyncSession, user: User, vm_id: int, forbidden: str) -> VirtualMachine:
    """ВМ под блокировкой; менять её может автор, участник его команды или администратор."""
    # FOR UPDATE: worker берёт ВМ из очереди через _take. Без блокировки отказ мог прочитать «queued», пока
    # клон уже запущен, и пометить ВМ удалённой — в vCenter осталась бы лишняя машина.
    vm = await session.scalar(
        select(VirtualMachine).where(VirtualMachine.id == vm_id).with_for_update(of=VirtualMachine)
        .execution_options(populate_existing=True)
    )
    if vm is None:
        raise NotFound("Виртуалка не найдена")
    ensure_access(user, vm.user_id, vm.department_id, forbidden)
    return vm


async def release(session: AsyncSession, user: User, vm_id: int) -> VirtualMachine:
    """Отказ от ВМ: worker выключит и удалит её в vSphere."""
    vm = await _lock_vm(session, user, vm_id,
                        "Удалить ВМ может тот, кто её заказывал, участник его команды или администратор")
    if vm.status in (VmStatus.deleting, VmStatus.deleted):
        raise Conflict("Виртуалка уже удаляется")
    if vm.status == VmStatus.creating:
        raise Conflict("Виртуалка ещё создаётся — подождите пару минут")
    vm.status = (VmStatus.deleting if vm.vsphere_moid else VmStatus.deleted).value  # в vCenter не создавалась — сразу
    vm.released_at = datetime.now(timezone.utc)
    vm.released_by_id = user.id
    if vm.status == VmStatus.deleted:
        vm.deleted_at = vm.released_at
    await session.commit()
    return await get_vm(session, vm.id)


async def extend(session: AsyncSession, user: User, vm_id: int, data: VmExtend) -> VirtualMachine:
    """Продление срока ВМ: сразу меняет срок и пишет продление в журнал. В Insight ВМ не записываются."""
    vm = await _lock_vm(session, user, vm_id,
                        "Продлить ВМ может тот, кто её заказывал, участник его команды или администратор")
    if vm.status in (VmStatus.deleting, VmStatus.deleted):
        raise Conflict("Виртуалка удаляется или уже удалена — продлить срок нельзя")
    old = vm.expected_return_at
    overdue.record_extension(session, user, old=old, new=data.expected_return_at, comment=data.comment,
                             vm_id=vm.id)
    vm.expected_return_at = data.expected_return_at
    await session.commit()
    return await get_vm(session, vm.id)


async def list_vms(session: AsyncSession, user: User | None = None, include_deleted: bool = True) -> list[VirtualMachine]:
    stmt = select(VirtualMachine).order_by(VirtualMachine.created_at.desc()).limit(500)
    if user is not None:
        stmt = stmt.where(mine_or_team(user, VirtualMachine.user_id, VirtualMachine.department_id))
    if not include_deleted:
        stmt = stmt.where(VirtualMachine.status != VmStatus.deleted)
    return list((await session.scalars(stmt)).unique().all())
