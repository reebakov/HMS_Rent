"""Шаблоны ОС конструктора ВМ: настройки (schemas.settings.VmTemplate), заявка (vms), воркер (vm_jobs), проверка vCenter.

vSphere — фейки: без pyVmomi-соединения и сети. Общие хелперы test_vm_jobs.py не импортируем, свои — ниже.
"""
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from pyVmomi import vim
from sqlalchemy import func, select

from app.core import clock
from app.core.config import settings
from app.core.errors import Conflict, DomainError
from app.db.session import SessionLocal
from app.integrations.vsphere import client as vsphere_client
from app.integrations.vsphere.client import ClusterUsage, VmInfo, VSphereError
from app.models import AppSetting, VirtualMachine
from app.schemas.settings import VmTemplate, default_templates
from app.schemas.vm import VmCreate, VmOut
from app.services import runtime, vm_jobs, vms
from app.services.runtime import RuntimeConfig

DEFAULT_KEYS = ["win10", "win11", "winsrv2022", "ubuntu2204"]


def tpl(key: str, template: str = "", **kw) -> dict:
    """Шаблон ОС как словарь (так он приходит в PATCH /admin/settings и хранится в app_settings)."""
    return {"key": key, "label": kw.pop("label", key.upper()), "template": template} | kw


async def set_templates(session, *items: dict) -> RuntimeConfig:
    return await runtime.update(session, {"vm_templates": list(items)})


class FakeVSphere:
    """Запоминает, с чем воркер вызвал create_vm (имя шаблона и спецификация гостевой настройки)."""

    def __init__(self):
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.sent: list[str] = []  # тексты уведомлений в Mattermost

    def create_vm(self, name, cpu, ram_gb, disk_gb, annotation, template_name=None, customization_spec=None):
        self.created.append({"name": name, "template": template_name, "spec": customization_spec})
        return VmInfo(moid=f"vm-{len(self.created)}", name=name, power_state="poweredOn", ip_address="10.0.0.5")

    def delete_vm(self, moid):
        self.deleted.append(moid)

    def cluster_usage(self):
        return ClusterUsage(cpu_total_mhz=1, cpu_used_mhz=0, ram_total_mb=10**7, ram_used_mb=0,
                            storage_total_mb=10**8, storage_used_mb=0)


@pytest.fixture
def vsphere(monkeypatch):
    fake = FakeVSphere()
    monkeypatch.setattr(vm_jobs, "vsphere", fake)

    async def record(text, *_a, **_kw):
        fake.sent.append(text)
    monkeypatch.setattr(vm_jobs, "notify", record)

    async def no_wait(_):
        pass
    monkeypatch.setattr(vm_jobs, "_pause", no_wait)
    return fake


@pytest.fixture
async def vm_on(session, monkeypatch):
    """vCenter «настроен», конструктор включён, шаблон win10 из настроек по умолчанию (Template_Win)."""
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)
    await runtime.update(session, {"vm_enabled": True})


@pytest.fixture
async def ctx(make_user, make_department):
    dept = await make_department("QA")
    return SimpleNamespace(dept=dept, user=await make_user("ivanov", department=dept))


TOMORROW = (clock.today() + timedelta(days=1)).isoformat()  # для JSON-тел запросов


def payload(dept_id: int, **kw) -> VmCreate:
    data = {"name": "dev-box", "cpu": 4, "ram_gb": 8, "disk_gb": 100, "department_id": dept_id,
            "requester_name": "Иван Иванов", "requester_nick": "ivan",
            "expected_return_at": clock.today() + timedelta(days=30)}
    return VmCreate(**(data | kw))


async def request(session, ctx, **kw) -> VirtualMachine:
    return await vms.create_request(session, ctx.user, payload(ctx.dept.id, **kw))


async def vm_count(session) -> int:
    return await session.scalar(select(func.count()).select_from(VirtualMachine))


async def stored_settings() -> dict:
    async with SessionLocal() as s:
        return {r.key: r.value for r in (await s.scalars(select(AppSetting))).all()}


@pytest.fixture
async def boss(login, make_user):
    user = await make_user("boss", role="admin")
    login(user)
    return user


# ---------- VmTemplate: валидация ----------

def test_template_defaults():
    t = VmTemplate(key="win10", label="Windows 10")
    assert (t.os, t.template, t.customization_spec, t.min_disk_gb, t.enabled) == ("windows", "", "", 50, True)


@pytest.mark.parametrize("kw", [
    {"key": "ab", "label": "OK"},  # нижние границы
    {"key": "a" * 32, "label": "x" * 64, "os": "linux", "min_disk_gb": 4096},  # верхние границы
    {"key": "a-b_9", "label": "Ubuntu", "os": "linux", "min_disk_gb": 10},
])
def test_template_accepts_valid(kw):
    assert VmTemplate(**kw).key == kw["key"]


@pytest.mark.parametrize("kw", [
    {"key": "a"}, {"key": "a" * 33}, {"key": "Win10"}, {"key": "win 10"}, {"key": "win.10"}, {"key": ""},  # key
    {"label": "x"}, {"label": "x" * 65}, {"label": ""},  # label
    {"os": "macos"}, {"os": "Windows"}, {"os": ""},  # os только windows|linux
    {"min_disk_gb": 9}, {"min_disk_gb": 4097}, {"min_disk_gb": "много"},  # диск
])
def test_template_rejects_invalid(kw):
    with pytest.raises(ValidationError):
        VmTemplate(**({"key": "win10", "label": "Windows 10"} | kw))


def test_template_requires_key_and_label():
    for kw in ({"label": "Windows"}, {"key": "win10"}):
        with pytest.raises(ValidationError):
            VmTemplate(**kw)


# ---------- значения по умолчанию ----------

def test_default_templates(monkeypatch):
    monkeypatch.setattr(settings, "vcenter_template_windows", "Tpl-W10")
    monkeypatch.setattr(settings, "vcenter_customization_spec", "sysprep-spec")
    by_key = {t.key: t for t in default_templates()}
    assert list(by_key) == DEFAULT_KEYS
    win10 = by_key["win10"]
    assert (win10.template, win10.customization_spec, win10.os, win10.enabled) == ("Tpl-W10", "sysprep-spec", "windows", True)
    for key in DEFAULT_KEYS[1:]:  # остальные — «скоро»: включены, но без имени шаблона
        assert (by_key[key].template, by_key[key].enabled) == ("", True)
    assert [by_key[k].os for k in DEFAULT_KEYS] == ["windows", "windows", "windows", "linux"]
    assert [by_key[k].min_disk_gb for k in DEFAULT_KEYS] == [50, 64, 60, 25]


def test_default_templates_are_taken_from_settings_at_call_time(monkeypatch):
    monkeypatch.setattr(settings, "vcenter_template_windows", "A")
    assert default_templates()[0].template == "A"
    monkeypatch.setattr(settings, "vcenter_template_windows", "B")
    assert RuntimeConfig().vm_templates[0].template == "B"


def test_runtime_config_defaults_are_independent_lists():
    a, b = RuntimeConfig(), RuntimeConfig()
    a.vm_templates[0].template = "changed"
    assert b.vm_templates[0].template != "changed"


# ---------- runtime.update / load ----------

async def test_update_stores_templates_as_json_list_of_dicts(session):
    cfg = await set_templates(session, tpl("win10", "T10", customization_spec="sp"), tpl("lin", "TL", os="linux"))
    assert [t.key for t in cfg.vm_templates] == ["win10", "lin"]
    stored = (await stored_settings())["vm_templates"]
    assert isinstance(stored, list) and all(isinstance(x, dict) for x in stored)
    assert stored[0] == {"key": "win10", "label": "WIN10", "os": "windows", "template": "T10",
                         "customization_spec": "sp", "min_disk_gb": 50, "enabled": True}  # с подставленными умолчаниями
    assert stored[1]["os"] == "linux"


async def test_update_accepts_model_instances(session):
    await runtime.update(session, {"vm_templates": [VmTemplate(key="win10", label="Win", template="T")]})
    assert (await stored_settings())["vm_templates"][0]["template"] == "T"


async def test_templates_roundtrip_through_db(session):
    await set_templates(session, tpl("win10", "T10", min_disk_gb=70, enabled=False))
    runtime._cache = (0.0, runtime._defaults())  # «другой процесс»: кэша нет, читаем из базы
    cfg = await runtime.load(session)
    assert cfg.vm_templates == [VmTemplate(key="win10", label="WIN10", template="T10", min_disk_gb=70, enabled=False)]


async def test_update_replaces_templates_list(session):
    await set_templates(session, tpl("aa", "1"), tpl("bb", "2"))
    await set_templates(session, tpl("cc", "3"))
    runtime._cache = (0.0, runtime._defaults())
    assert [t.key for t in (await runtime.load(session)).vm_templates] == ["cc"]
    async with SessionLocal() as s:  # одна строка, не две
        assert await s.scalar(select(func.count()).select_from(AppSetting).where(AppSetting.key == "vm_templates")) == 1


async def test_update_other_setting_does_not_store_or_touch_templates(session):
    await runtime.update(session, {"vm_max_per_user": 3})
    assert set(await stored_settings()) == {"vm_max_per_user"}  # шаблоны по умолчанию в базу не пишутся
    await set_templates(session, tpl("aa", "1"))
    await runtime.update(session, {"vm_max_per_user": 4})
    runtime._cache = (0.0, runtime._defaults())
    cfg = await runtime.load(session)
    assert [t.key for t in cfg.vm_templates] == ["aa"] and cfg.vm_max_per_user == 4


async def test_templates_update_keeps_other_settings(session):
    await runtime.update(session, {"vm_max_per_user": 7, "catalog_refresh_sec": 30})
    await set_templates(session, tpl("aa", "1"))
    runtime._cache = (0.0, runtime._defaults())
    cfg = await runtime.load(session)
    assert (cfg.vm_max_per_user, cfg.catalog_refresh_sec) == (7, 30)


async def test_load_without_stored_templates_gives_defaults(session):
    assert [t.key for t in (await runtime.load(session, max_age=0)).vm_templates] == DEFAULT_KEYS


@pytest.mark.parametrize("broken", [
    [{"key": "X", "label": "Windows"}],  # key не по шаблону
    [{"label": "без ключа"}],
    "не список",
    [{"key": "win10", "label": "Windows", "min_disk_gb": 1}],
])
async def test_broken_templates_in_db_fall_back_to_defaults(session, broken):
    session.add(AppSetting(key="vm_templates", value=broken))
    await session.commit()
    cfg = await runtime.load(session, max_age=0)  # портал не падает
    assert [t.key for t in cfg.vm_templates] == DEFAULT_KEYS


@pytest.mark.parametrize("bad", [
    [{"key": "X", "label": "Windows"}], [{"key": "win10"}], [{"key": "win10", "label": "W", "os": "bsd"}],
    [{"key": "win10", "label": "Windows", "min_disk_gb": 5}], "строка", {"key": "win10"}, [1],
])
async def test_update_rejects_invalid_templates_before_writing(session, bad):
    with pytest.raises(ValueError):
        await runtime.update(session, {"vm_templates": bad})
    assert await stored_settings() == {}
    assert [t.key for t in runtime.current().vm_templates] == DEFAULT_KEYS


async def test_update_rejects_duplicate_template_keys(session):
    with pytest.raises(ValueError, match="уникальными"):
        await set_templates(session, tpl("aa", "1"), tpl("bb", "2"), tpl("aa", "3"))
    assert await stored_settings() == {}
    assert [t.key for t in runtime.current().vm_templates] == DEFAULT_KEYS


async def test_stored_duplicate_keys_do_not_block_other_settings(session):
    """Дубли, сохранённые до проверки, остаются как есть: остальные настройки по-прежнему меняются."""
    dup = [tpl("aa", "1"), tpl("aa", "2")]
    session.add(AppSetting(key="vm_templates", value=dup))
    await session.commit()
    cfg = await runtime.update(session, {"vm_max_per_user": 4})
    assert cfg.vm_max_per_user == 4 and [t.key for t in cfg.vm_templates] == ["aa", "aa"]


def test_template_text_fields_are_trimmed_and_blank_label_rejected():
    t = VmTemplate(**tpl("aa", "  Tpl-1  ", label="  Windows  ", customization_spec=" spec "))
    assert (t.label, t.template, t.customization_spec) == ("Windows", "Tpl-1", "spec")
    with pytest.raises(ValueError):
        VmTemplate(**tpl("aa", label="    "))


async def test_empty_templates_list_is_allowed(session):
    assert (await set_templates(session)).vm_templates == []
    assert (await stored_settings())["vm_templates"] == []


# ---------- PATCH / GET /admin/settings ----------

async def test_patch_settings_updates_templates(client, boss, api, session):
    r = await client.patch(api("/admin/settings"), json={"vm_templates": [tpl("ubuntu2204", "Tpl-U", os="linux",
                                                                               customization_spec="lin-spec")]})
    assert r.status_code == 200
    (t,) = r.json()["vm_templates"]
    assert (t["key"], t["template"], t["os"], t["customization_spec"], t["enabled"]) == (
        "ubuntu2204", "Tpl-U", "linux", "lin-spec", True)
    assert (await client.get(api("/admin/settings"))).json()["vm_templates"] == [t]
    assert (await stored_settings())["vm_templates"] == [t]
    assert [x.key for x in runtime.current().vm_templates] == ["ubuntu2204"]


async def test_patch_settings_rejects_duplicate_template_keys(client, boss, api):
    r = await client.patch(api("/admin/settings"), json={"vm_templates": [tpl("aa", "1"), tpl("aa", "2")]})
    assert r.status_code == 422 and "уникальными" in r.json()["detail"]
    assert await stored_settings() == {}


async def test_patch_settings_templates_do_not_clobber_other_settings(client, boss, api):
    await client.patch(api("/admin/settings"), json={"vm_max_per_user": 5, "vm_enabled": True})
    body = (await client.patch(api("/admin/settings"), json={"vm_templates": [tpl("aa", "1")]})).json()
    assert body["vm_max_per_user"] == 5 and body["vm_enabled"] is True
    body = (await client.patch(api("/admin/settings"), json={"catalog_refresh_sec": 30})).json()  # и наоборот
    assert [t["key"] for t in body["vm_templates"]] == ["aa"] and body["vm_max_per_user"] == 5
    assert set(await stored_settings()) == {"vm_max_per_user", "vm_enabled", "vm_templates", "catalog_refresh_sec"}


@pytest.mark.parametrize("bad", [
    [{"key": "Bad Key", "label": "Windows"}], [{"key": "win10", "label": "W"}],
    [{"key": "win10", "label": "Windows", "os": "macos"}], [{"key": "win10", "label": "Windows", "min_disk_gb": 9}],
    [{"key": "win10", "label": "Windows", "min_disk_gb": 5000}], "не список", [{"label": "без ключа"}],
])
async def test_patch_settings_invalid_template_is_422_and_changes_nothing(client, boss, api, bad):
    r = await client.patch(api("/admin/settings"), json={"vm_max_per_user": 5, "vm_templates": bad})
    assert r.status_code == 422
    assert await stored_settings() == {}  # даже вместе с валидным полем ничего не записано
    assert [t["key"] for t in (await client.get(api("/admin/settings"))).json()["vm_templates"]] == DEFAULT_KEYS


async def test_get_settings_defaults_include_four_templates(client, boss, api):
    templates = (await client.get(api("/admin/settings"))).json()["vm_templates"]
    assert [t["key"] for t in templates] == DEFAULT_KEYS
    assert templates[0]["template"] == settings.vcenter_template_windows and templates[1]["template"] == ""


async def test_get_settings_broken_templates_fall_back_to_defaults(client, boss, api, session):
    session.add(AppSetting(key="vm_templates", value=[{"key": "BAD"}]))
    await session.commit()
    r = await client.get(api("/admin/settings"))
    assert r.status_code == 200 and [t["key"] for t in r.json()["vm_templates"]] == DEFAULT_KEYS


# ---------- vms.options ----------

async def test_options_default_templates(session, vm_on, ctx):
    opts = await vms.options(session, ctx.user)
    assert opts.enabled and opts.reason is None and opts.template == "Windows 10"
    got = {t.key: t for t in opts.templates}
    assert list(got) == DEFAULT_KEYS
    assert [got[k].available for k in DEFAULT_KEYS] == [True, False, False, False]  # без шаблона в vCenter — «скоро»
    assert (got["win10"].label, got["win10"].os) == ("Windows 10", "windows") and got["ubuntu2204"].os == "linux"
    # min_disk = больше из диска шаблона и общего минимума (vm_min_disk_gb=50)
    assert [got[k].min_disk_gb for k in DEFAULT_KEYS] == [50, 64, 60, 50]


async def test_options_hide_disabled_and_show_unconfigured(session, vm_on, ctx):
    await set_templates(session, tpl("aa", "Tpl", label="Alpha"), tpl("bb", "", label="Beta"),
                        tpl("cc", "Tpl-C", label="Gamma", enabled=False))
    opts = await vms.options(session, ctx.user)
    assert [(t.key, t.available) for t in opts.templates] == [("aa", True), ("bb", False)]  # выключенного нет вовсе
    assert opts.enabled and opts.template == "Alpha"


async def test_options_template_is_first_available_label(session, vm_on, ctx):
    await set_templates(session, tpl("aa", "Tpl", label="Alpha", enabled=False), tpl("bb", "", label="Beta"),
                        tpl("cc", "Tpl-C", label="Gamma"))
    assert (await vms.options(session, ctx.user)).template == "Gamma"


@pytest.mark.parametrize("items", [
    [],  # список пуст
    [tpl("aa", "", label="Alpha")],  # все «скоро»
    [tpl("aa", "Tpl", label="Alpha", enabled=False)],  # всё выключено
])
async def test_options_no_available_templates(session, vm_on, ctx, items):
    await set_templates(session, *items)
    opts = await vms.options(session, ctx.user)
    assert opts.enabled is False and "Нет настроенных шаблонов ОС" in opts.reason and opts.template == "—"
    assert [t.available for t in opts.templates] == [False] * sum(t.get("enabled", True) for t in items)


async def test_options_reason_priority(session, vm_on, ctx, monkeypatch):
    """vCenter -> выключено админом -> нет шаблонов -> лимит на пользователя."""
    await set_templates(session)
    await runtime.update(session, {"vm_max_per_user": 1})
    assert "Нет настроенных шаблонов" in (await vms.options(session, ctx.user)).reason
    await runtime.update(session, {"vm_enabled": False})
    assert "выключен" in (await vms.options(session, ctx.user)).reason
    monkeypatch.setattr(settings, "vcenter_host", "")
    assert "не подключён" in (await vms.options(session, ctx.user)).reason


async def test_options_limit_reason_when_templates_ok(session, vm_on, ctx, vsphere):
    await runtime.update(session, {"vm_max_per_user": 1})
    await request(session, ctx)
    opts = await vms.options(session, ctx.user)
    assert not opts.enabled and "1 из 1" in opts.reason and opts.used_by_me == 1


async def test_options_template_min_disk_never_below_global_min(session, vm_on, ctx):
    await runtime.update(session, {"vm_min_disk_gb": 80})
    await set_templates(session, tpl("aa", "T", min_disk_gb=25), tpl("bb", "T", min_disk_gb=120))
    assert [t.min_disk_gb for t in (await vms.options(session, ctx.user)).templates] == [80, 120]


async def test_options_api_returns_templates(client, login, api, vm_on, ctx):
    login(ctx.user)
    body = (await client.get(api("/vms/options"))).json()
    assert body["template"] == "Windows 10"
    assert body["templates"][0] == {"key": "win10", "label": "Windows 10", "os": "windows", "min_disk_gb": 50,
                                    "available": True}
    assert [t["available"] for t in body["templates"]] == [True, False, False, False]


# ---------- vms.create_request ----------

@pytest.mark.parametrize("key", [None, ""])
async def test_create_without_template_key_uses_first_available(session, vm_on, ctx, key):
    vm = await request(session, ctx, template_key=key)
    assert (vm.template_key, vm.os_label) == ("win10", "Windows 10")


async def test_create_default_skips_disabled_and_unconfigured(session, vm_on, ctx):
    await set_templates(session, tpl("aa", "", label="Alpha"), tpl("bb", "TB", label="Beta", enabled=False),
                        tpl("cc", "TC", label="Gamma"))
    vm = await request(session, ctx)
    assert (vm.template_key, vm.os_label) == ("cc", "Gamma")


async def test_create_with_explicit_template(session, vm_on, ctx):
    await set_templates(session, tpl("win10", "T10", label="Windows 10"),
                        tpl("ubuntu2204", "TU", label="Ubuntu 22.04", os="linux", min_disk_gb=25))
    vm = await request(session, ctx, template_key="ubuntu2204")
    assert (vm.template_key, vm.os_label, vm.status) == ("ubuntu2204", "Ubuntu 22.04", "queued")


@pytest.mark.parametrize("key", [
    "nope",  # неизвестный ключ
    "win11",  # включён, но шаблон не настроен («скоро»)
    "old",  # настроен, но выключен
])
async def test_create_unavailable_template_rejected(session, vm_on, ctx, key):
    await set_templates(session, tpl("win10", "T10"), tpl("win11", ""), tpl("old", "TO", enabled=False))
    with pytest.raises(DomainError, match="Эта ОС пока недоступна"):
        await request(session, ctx, template_key=key)
    assert await vm_count(session) == 0  # заявка не создана, номер заказа не потрачен


async def test_create_with_only_default_ubuntu_unconfigured_is_unavailable(session, vm_on, ctx):
    with pytest.raises(DomainError, match="Эта ОС пока недоступна"):
        await request(session, ctx, template_key="ubuntu2204")


async def test_create_no_templates_rejected_as_conflict(session, vm_on, ctx):
    await set_templates(session)  # options.enabled=False -> Conflict с понятной причиной раньше, чем «ОС недоступна»
    with pytest.raises(Conflict, match="Нет настроенных шаблонов ОС"):
        await request(session, ctx)


async def test_create_disk_below_template_min_rejected(session, vm_on, ctx):
    await set_templates(session, tpl("win11", "T11", label="Windows 11", min_disk_gb=64))
    with pytest.raises(DomainError, match="Для Windows 11 диск — не меньше 64 ГБ"):
        await request(session, ctx, template_key="win11", disk_gb=63)
    assert await vm_count(session) == 0
    assert (await request(session, ctx, template_key="win11", disk_gb=64)).disk_gb == 64  # граница включена


async def test_create_template_min_disk_applies_to_default_template_too(session, vm_on, ctx):
    await set_templates(session, tpl("win11", "T11", label="Windows 11", min_disk_gb=64))
    with pytest.raises(DomainError, match="не меньше 64"):
        await request(session, ctx, disk_gb=60)  # ключ не указан -> первый доступный


async def test_create_template_min_below_global_min_uses_global_limit(session, vm_on, ctx):
    await runtime.update(session, {"vm_min_disk_gb": 20})
    await set_templates(session, tpl("ubuntu2204", "TU", label="Ubuntu", os="linux", min_disk_gb=25))
    with pytest.raises(DomainError, match="от 20 до 200"):
        await request(session, ctx, disk_gb=19)  # общий минимум проверяется раньше шаблонного
    with pytest.raises(DomainError, match="не меньше 25"):
        await request(session, ctx, disk_gb=24)
    assert (await request(session, ctx, disk_gb=25)).disk_gb == 25


async def test_create_follows_template_update(session, vm_on, ctx):
    """Админ сохранил настройки — следующая заявка видит новые шаблоны без перезапуска."""
    with pytest.raises(DomainError):
        await request(session, ctx, template_key="win11")
    await set_templates(session, tpl("win11", "T11", label="Windows 11"))
    assert (await request(session, ctx, template_key="win11")).os_label == "Windows 11"


async def test_create_checks_still_come_before_template(session, vm_on, ctx):
    """Отключено / лимит на пользователя / диапазоны — как и раньше, независимо от шаблона."""
    with pytest.raises(DomainError, match="от 2 до 8"):
        await request(session, ctx, template_key="nope", cpu=64)  # ядра важнее «ОС недоступна»
    await runtime.update(session, {"vm_max_per_user": 1})
    await request(session, ctx, name="vm-one")
    with pytest.raises(Conflict, match="1 из 1"):
        await request(session, ctx, name="vm-two", template_key="nope")
    await runtime.update(session, {"vm_enabled": False})
    with pytest.raises(Conflict, match="выключен"):
        await request(session, ctx, name="vm-three", template_key="nope")


async def test_admin_create_unknown_department_still_rejected(session, vm_on, ctx, make_user):
    admin = await make_user("root", role="admin")
    with pytest.raises(DomainError, match="Отдел"):
        await vms.create_request(session, admin, payload(9999))


# ---------- API и схема вывода ----------

async def test_create_api_saves_template_and_returns_it(client, login, api, session, vm_on, ctx):
    login(ctx.user)
    await set_templates(session, tpl("win10", "T10", label="Windows 10"))
    body = {"name": "api-box", "cpu": 2, "ram_gb": 4, "disk_gb": 50, "department_id": ctx.dept.id,
            "requester_name": "Иван", "requester_nick": "iv", "expected_return_at": TOMORROW}
    r = await client.post(api("/vms"), json=body | {"template_key": "win10"})
    assert r.status_code == 201
    assert (r.json()["template_key"], r.json()["os_label"]) == ("win10", "Windows 10")
    bad = await client.post(api("/vms"), json=body | {"name": "bad-box", "template_key": "ubuntu2204"})
    assert bad.status_code == 400 and "Эта ОС пока недоступна" in bad.json()["detail"]
    r = await client.post(api("/vms"), json=body | {"name": "dflt-box"})  # без template_key — первый доступный
    assert r.status_code == 201 and r.json()["template_key"] == "win10"


async def test_legacy_vm_without_template_is_listed(client, login, api, session, vm_on, ctx, make_user):
    """ВМ, созданные до шаблонов (template_key/os_label = NULL), отображаются без ошибок."""
    vm = await request(session, ctx)
    vm.template_key = vm.os_label = None
    await session.commit()
    login(ctx.user)
    (mine,) = (await client.get(api("/vms/my"))).json()
    assert mine["template_key"] is None and mine["os_label"] is None and mine["name"] == vm.name
    boss = await make_user("boss", role="admin")
    login(boss)
    (adm,) = (await client.get(api("/admin/vms"))).json()
    assert adm["template_key"] is None and adm["os_label"] is None


async def test_vm_out_schema_optional_template_fields(session, vm_on, ctx):
    vm = await request(session, ctx)
    assert (VmOut.model_validate(vm).template_key, VmOut.model_validate(vm).os_label) == ("win10", "Windows 10")
    vm.template_key = vm.os_label = None
    out = VmOut.model_validate(vm)
    assert out.template_key is None and out.os_label is None


def test_vm_create_template_key_is_optional():
    assert payload(1).template_key is None
    assert payload(1, template_key="win10").template_key == "win10"


# ---------- vm_jobs.create_next ----------

async def test_create_next_passes_selected_template_and_spec(session, vm_on, ctx, vsphere):
    await set_templates(session, tpl("win10", "T10", customization_spec="spec-w"),
                        tpl("ubuntu2204", "TU", os="linux", customization_spec="spec-l", min_disk_gb=25))
    vm = await request(session, ctx, template_key="ubuntu2204")
    assert await vm_jobs.create_next(session) is True
    assert vsphere.created == [{"name": vm.name, "template": "TU", "spec": "spec-l"}]


async def test_create_next_default_template_comes_from_settings(session, vm_on, ctx, vsphere, monkeypatch):
    monkeypatch.setattr(settings, "vcenter_template_windows", "Tpl-W10")
    monkeypatch.setattr(settings, "vcenter_customization_spec", "sysprep")
    await runtime.update(session, {"vm_templates": [t.model_dump() for t in default_templates()]})
    await request(session, ctx)
    await vm_jobs.create_next(session)
    assert [(c["template"], c["spec"]) for c in vsphere.created] == [("Tpl-W10", "sysprep")]


async def test_create_next_empty_spec_is_passed_as_empty_string(session, vm_on, ctx, vsphere):
    """Пустая спецификация шаблона — «без гостевой настройки» (не None): общий VCENTER_CUSTOMIZATION_SPEC не подмешивается."""
    await set_templates(session, tpl("win10", "T10"))
    await request(session, ctx)
    await vm_jobs.create_next(session)
    assert vsphere.created[0]["template"] == "T10" and vsphere.created[0]["spec"] == ""


async def test_create_next_uses_settings_changed_after_queueing(session, vm_on, ctx, vsphere):
    """Шаблон берётся в момент создания: админ поправил имя шаблона/спецификацию, пока заявка стояла в очереди."""
    await set_templates(session, tpl("win10", "Old"))
    await request(session, ctx)
    await set_templates(session, tpl("win10", "New", customization_spec="sp2"))
    await vm_jobs.create_next(session)
    assert [(c["template"], c["spec"]) for c in vsphere.created] == [("New", "sp2")]


async def test_create_next_legacy_vm_without_template_key_uses_vcenter_defaults(session, vm_on, ctx, vsphere):
    """template_key=NULL (заявка до введения шаблонов) -> (None, None): клиент vSphere берёт настройки из .env."""
    vm = await request(session, ctx)
    vm_id, name = vm.id, vm.name
    vm.template_key = vm.os_label = None
    await session.commit()
    await vm_jobs.create_next(session)
    assert vsphere.created == [{"name": name, "template": None, "spec": None}]
    session.expire_all()
    assert (await session.get(VirtualMachine, vm_id)).status == "ready"


@pytest.mark.parametrize("change", [
    pytest.param(lambda: [tpl("win10", "T10")], id="removed-from-settings"),
    pytest.param(lambda: [tpl("win10", "T10"), tpl("ubuntu2204", "", os="linux")], id="name-cleared"),
])
async def test_create_next_vanished_template_does_not_fall_back_to_windows(session, vm_on, ctx, vsphere, change):
    await set_templates(session, tpl("win10", "T10"), tpl("ubuntu2204", "TU", os="linux", min_disk_gb=25))
    vm_id = (await request(session, ctx, template_key="ubuntu2204")).id
    await set_templates(session, *change())
    await vm_jobs.create_next(session)
    session.expire_all()
    vm = await session.get(VirtualMachine, vm_id)
    assert vm.status == "failed" and "больше не доступен" in vm.error
    assert any("больше не доступен" in text for text in vsphere.sent)  # исполнители узнают и об этой ошибке
    assert vsphere.created == []  # Linux-ВМ не должна создаваться из Windows-шаблона


async def test_create_next_disabled_template_with_name_still_creates(session, vm_on, ctx, vsphere):
    """Выключение шаблона скрывает его для новых заявок, но уже стоящая в очереди ВМ создаётся из него."""
    await set_templates(session, tpl("win10", "T10"), tpl("ubuntu2204", "TU", os="linux", min_disk_gb=25))
    await request(session, ctx, template_key="ubuntu2204")
    await set_templates(session, tpl("win10", "T10"), tpl("ubuntu2204", "TU", os="linux", min_disk_gb=25, enabled=False))
    await vm_jobs.create_next(session)
    assert vsphere.created[0]["template"] == "TU"


# ---------- POST /admin/vsphere/check ----------

@pytest.fixture
def fake_check(monkeypatch):
    calls: list = []

    def check(names=None):
        calls.append(names)
        return {"vcenter": "vc.local", "templates": {n: True for n in names}}
    monkeypatch.setattr(vsphere_client, "check", check)
    return calls


async def test_vsphere_check_default_passes_win10_template(client, boss, api, fake_check):
    r = await client.post(api("/admin/vsphere/check"))
    assert r.status_code == 200 and fake_check == [[settings.vcenter_template_windows]]
    assert r.json()["templates"] == {settings.vcenter_template_windows: True}  # ответ vsphere.check отдаётся как есть


async def test_vsphere_check_passes_names_of_enabled_configured_templates(client, boss, api, session, fake_check):
    await set_templates(session, tpl("win10", "T10"), tpl("win11", ""), tpl("old", "TOld", enabled=False),
                        tpl("ubuntu2204", "TU", os="linux"))
    r = await client.post(api("/admin/vsphere/check"))
    assert r.json()["ok"] is True and fake_check == [["T10", "TU"]]  # без пустых и выключенных, в порядке списка


async def test_vsphere_check_without_templates_passes_empty_list(client, boss, api, session, fake_check):
    await set_templates(session)
    await client.post(api("/admin/vsphere/check"))
    assert fake_check == [[]]


# ---------- vsphere/client.py на подменённых объектах ----------

class FakeInventory:
    """Подмена _find: объекты vCenter по (тип, имя). Остальной pyVmomi не нужен — типы только для isinstance."""

    def __init__(self, **found):
        self.found = found  # имя -> объект (имена в тестах уникальны между типами)
        self.asked: list[tuple] = []

    def __call__(self, si, vimtype, name, root=None):
        self.asked.append((vimtype, name))
        return self.found.get(name)


def fake_template(name: str, disk_kb: int = 60 * 1024 * 1024):
    disk = vim.vm.device.VirtualDisk(capacityInKB=disk_kb)
    hw = SimpleNamespace(numCPU=2, memoryMB=4096, device=[disk])
    return SimpleNamespace(name=name, config=SimpleNamespace(hardware=hw))


def inventory(*templates, **extra) -> FakeInventory:
    base = {settings.vcenter_datacenter: SimpleNamespace(name="DC", vmFolder=SimpleNamespace(name="vm", childEntity=[]),
                                                          hostFolder=None, datastoreFolder=None),
            settings.vcenter_cluster: object(), settings.vcenter_resource_pool: SimpleNamespace(name="Rent")}
    return FakeInventory(**base | {t.name: t for t in templates} | extra)


@pytest.fixture
def vc(monkeypatch):
    """vc(inv) — подменяет connect() и поиск объектов в клиенте vSphere."""
    @contextmanager
    def fake_connect():
        yield SimpleNamespace()

    def _set(inv: FakeInventory) -> FakeInventory:
        monkeypatch.setattr(vsphere_client, "connect", fake_connect)
        monkeypatch.setattr(vsphere_client, "_find", inv)
        return inv
    return _set


def test_placement_uses_given_template_name(vc):
    inv = vc(inventory(fake_template("T-Ubuntu")))
    *_, template = vsphere_client._placement(SimpleNamespace(), "T-Ubuntu")
    assert template.name == "T-Ubuntu" and (vim.VirtualMachine, "T-Ubuntu") in inv.asked


@pytest.mark.parametrize("name", [None, ""])
def test_placement_falls_back_to_windows_template_from_settings(vc, name):
    vc(inventory(fake_template(settings.vcenter_template_windows)))
    *_, template = vsphere_client._placement(SimpleNamespace(), name)
    assert template.name == settings.vcenter_template_windows


def test_placement_missing_template_error_names_it(vc):
    vc(inventory())
    with pytest.raises(VSphereError, match="Не найден шаблон «Нет-такого»"):
        vsphere_client._placement(SimpleNamespace(), "Нет-такого")


def test_check_reports_which_templates_exist(vc):
    vc(inventory(fake_template(settings.vcenter_template_windows), fake_template("T-Ubuntu")))
    info = vsphere_client.check(["T-Ubuntu", "T-Missing"])
    assert info["templates"] == {"T-Ubuntu": True, "T-Missing": False}
    assert info["template"] == settings.vcenter_template_windows and info["template_disk_gb"] == 60
    assert (info["template_cpu"], info["template_ram_gb"]) == (2, 4)


@pytest.mark.parametrize("names", [None, []])
def test_check_without_names_has_empty_templates(vc, names):
    vc(inventory(fake_template(settings.vcenter_template_windows)))
    assert vsphere_client.check(names)["templates"] == {}


def test_check_fails_when_default_template_missing(vc):
    vc(inventory(fake_template("T-Ubuntu")))
    with pytest.raises(VSphereError, match="Не найден шаблон"):
        vsphere_client.check(["T-Ubuntu"])  # основной (Windows по умолчанию) шаблон обязателен, как и раньше


class FakeCloneTemplate:
    """Шаблон, у которого CloneVM_Task запоминает spec; клон — пустая ВМ без дисков и сетевых карт."""

    def __init__(self):
        self.name = "T"
        self.clone_spec = None
        self.clone_name = None
        self.vm = SimpleNamespace(
            _moId="vm-9", name="clone", config=SimpleNamespace(hardware=SimpleNamespace(device=[])),
            runtime=SimpleNamespace(powerState="poweredOn"), guest=SimpleNamespace(ipAddress="10.1.1.1"),
            PowerOnVM_Task=lambda: None,
        )

    def CloneVM_Task(self, folder, name, spec):  # noqa: N802 — имя метода pyVmomi
        self.clone_spec, self.clone_name = spec, name
        return self.vm


@pytest.fixture
def clone(monkeypatch):
    """clone(identity) -> (шаблон, список имён запрошенных спецификаций, переданное имя шаблона)."""
    def _set(identity):
        template = FakeCloneTemplate()
        asked_specs: list[str] = []
        placement_names: list = []
        manager = SimpleNamespace(GetCustomizationSpec=lambda n: asked_specs.append(n) or SimpleNamespace(
            spec=vim.vm.customization.Specification(identity=identity)))
        si = SimpleNamespace(content=SimpleNamespace(customizationSpecManager=manager))

        @contextmanager
        def fake_connect():
            yield si

        def fake_placement(_si, template_name=None):
            placement_names.append(template_name)
            return None, vim.ResourcePool("pool-1"), None, template
        monkeypatch.setattr(vsphere_client, "connect", fake_connect)
        monkeypatch.setattr(vsphere_client, "_find", lambda *a, **k: None)  # имя ВМ в vCenter свободно
        monkeypatch.setattr(vsphere_client, "_placement", fake_placement)
        monkeypatch.setattr(vsphere_client, "_wait", lambda task, what, timeout=0: task)
        return template, asked_specs, placement_names
    return _set


def sysprep():
    return vim.vm.customization.Sysprep(userData=vim.vm.customization.UserData(
        computerName=vim.vm.customization.FixedName(name="x")))


def test_create_vm_windows_spec_sets_computer_name_up_to_15_chars(clone):
    template, asked, placed = clone(sysprep())
    info = vsphere_client.create_vm("A1234567890123456", 2, 4, 50, "note", "T-Win", "spec-win")
    assert placed == ["T-Win"] and asked == ["spec-win"]
    assert template.clone_name == "A1234567890123456"
    assert template.clone_spec.customization.identity.userData.computerName.name == "A12345678901234"
    assert (info.moid, info.ip_address) == ("vm-9", "10.1.1.1")


def test_create_vm_linux_spec_sets_hostname_up_to_63_chars(clone):
    template, asked, _ = clone(vim.vm.customization.LinuxPrep(hostName=vim.vm.customization.FixedName(name="x"),
                                                              domain="corp.local"))
    vsphere_client.create_vm("A1010", 2, 4, 30, "note", "T-Ubu", "spec-lin")
    assert asked == ["spec-lin"]
    assert template.clone_spec.customization.identity.hostName.name == "A1010"


def test_create_vm_customization_spec_none_falls_back_to_env(clone, monkeypatch):
    monkeypatch.setattr(settings, "vcenter_customization_spec", "env-spec")
    template, asked, placed = clone(sysprep())
    vsphere_client.create_vm("A1006", 2, 4, 50, "note")  # старый вызов без шаблона: поведение прежнее
    assert placed == [None] and asked == ["env-spec"] and template.clone_spec.customization is not None


def test_create_vm_empty_spec_means_no_customization(clone, monkeypatch):
    monkeypatch.setattr(settings, "vcenter_customization_spec", "env-spec")
    template, asked, _ = clone(sysprep())
    vsphere_client.create_vm("A1006", 2, 4, 50, "note", "T", "")
    assert asked == [] and template.clone_spec.customization is None


def test_create_vm_rejects_existing_name(monkeypatch, vc):
    vc(inventory(fake_template("T"), **{"A1006": object()}))
    with pytest.raises(VSphereError, match="уже есть в vCenter"):
        vsphere_client.create_vm("A1006", 2, 4, 50, "note", "T")
