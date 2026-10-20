"""Готовые размеры ВМ (schemas.settings.VmSize): настройки, проверка уникальности и выдача в конструктор (vms.options)."""
import pytest
from pydantic import ValidationError

from app.schemas.settings import VmSize, default_vm_sizes
from app.services import runtime, vms
from tests.test_vm_templates import boss, ctx, vm_on  # noqa: F401 — фикстуры


def size(label: str, cpu: int = 2, ram_gb: int = 4, disk_gb: int = 50) -> dict:
    return {"label": label, "cpu": cpu, "ram_gb": ram_gb, "disk_gb": disk_gb}


def test_default_sizes_are_s_m_l():
    assert [(s.label, s.cpu, s.ram_gb, s.disk_gb) for s in default_vm_sizes()] == [
        ("S", 2, 4, 50), ("M", 4, 8, 100), ("L", 8, 16, 200)]


@pytest.mark.parametrize("bad", [
    {"label": ""}, {"label": "   "}, {"label": "x" * 33}, {"cpu": 0}, {"cpu": 65}, {"ram_gb": 0}, {"disk_gb": 9},
    {"disk_gb": 4097},
], ids=["empty", "blank", "long", "cpu0", "cpu65", "ram0", "disk9", "disk-max"])
def test_size_rejects_invalid(bad):
    with pytest.raises(ValidationError):
        VmSize(**(size("S") | bad))


async def test_update_stores_sizes(session):
    cfg = await runtime.update(session, {"vm_sizes": [size("XS", 1, 2, 20), size("XL", 16, 64, 500)]})
    assert [s.label for s in cfg.vm_sizes] == ["XS", "XL"]
    assert [s.label for s in (await runtime.load(session, max_age=0)).vm_sizes] == ["XS", "XL"]


async def test_update_rejects_duplicate_labels(session):
    with pytest.raises(ValueError, match="размеров ВМ должны быть уникальными"):
        await runtime.update(session, {"vm_sizes": [size("S"), size("S", 4, 8, 100)]})
    assert [s.label for s in (await runtime.load(session, max_age=0)).vm_sizes] == ["S", "M", "L"]


async def test_patch_settings_updates_sizes(client, boss, api):  # noqa: F811
    r = await client.patch(api("/admin/settings"), json={"vm_sizes": [size("Мини", 2, 4, 60)]})
    assert r.status_code == 200, r.text
    assert r.json()["vm_sizes"] == [size("Мини", 2, 4, 60)]
    assert (await client.get(api("/admin/settings"))).json()["vm_sizes"] == [size("Мини", 2, 4, 60)]


async def test_patch_settings_invalid_size_is_422(client, boss, api):  # noqa: F811
    r = await client.patch(api("/admin/settings"), json={"vm_sizes": [size("S", cpu=0)]})
    assert r.status_code == 422


async def test_options_give_default_sizes(session, vm_on, ctx):  # noqa: F811
    opts = await vms.options(session, ctx.user)
    assert [s.label for s in opts.sizes] == ["S", "M", "L"]


async def test_options_hide_sizes_outside_limits(session, vm_on, ctx):  # noqa: F811
    await runtime.update(session, {"vm_max_cpu": 4, "vm_sizes": [
        size("ok", 4, 8, 100), size("cpu", 8, 8, 100), size("ram", 2, 1, 50), size("disk", 2, 4, 1000)]})
    assert [s.label for s in (await vms.options(session, ctx.user)).sizes] == ["ok"]


async def test_options_api_returns_sizes(client, login, api, vm_on, ctx):  # noqa: F811
    login(ctx.user)
    body = (await client.get(api("/vms/options"))).json()
    assert body["sizes"][0] == size("S", 2, 4, 50)
