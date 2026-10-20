"""Мощности кластера: проверка перед созданием ВМ, сводка для админки и маршрут /admin/cluster."""
import pytest

from app.core.config import settings
from app.integrations.vsphere import client as vsphere_client
from app.integrations.vsphere.client import ClusterUsage, VSphereError
from app.services import capacity

GB = 1024


def usage(ram_free_gb=100, storage_free_gb=1000, cpu_free_mhz=50_000) -> ClusterUsage:
    return ClusterUsage(cpu_total_mhz=100_000, cpu_used_mhz=100_000 - cpu_free_mhz,
                        ram_total_mb=512 * GB, ram_used_mb=(512 - ram_free_gb) * GB,
                        storage_total_mb=2000 * GB, storage_used_mb=(2000 - storage_free_gb) * GB)


@pytest.mark.parametrize("free_ram, free_disk, expected", [
    (100, 1000, None),
    (8, 1000, None),  # ровно хватает — можно
    (4, 1000, "памяти: нужно 8 ГБ, свободно 4 ГБ"),
    (100, 50, "диска: нужно 100 ГБ, свободно 50 ГБ"),
    (4, 50, "памяти: нужно 8 ГБ, свободно 4 ГБ; диска: нужно 100 ГБ, свободно 50 ГБ"),
])
def test_shortage(free_ram, free_disk, expected):
    result = capacity.shortage(usage(ram_free_gb=free_ram, storage_free_gb=free_disk), ram_gb=8, disk_gb=100)
    assert result == (f"Недостаточно мощностей кластера, не хватает {expected}" if expected else None)


def test_shortage_ignores_cpu():
    assert capacity.shortage(usage(cpu_free_mhz=0), ram_gb=8, disk_gb=100) is None


@pytest.fixture
def vcenter(monkeypatch):
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)


async def test_summary_converts_units(vcenter, monkeypatch):
    monkeypatch.setattr(vsphere_client, "cluster_usage", lambda: usage(ram_free_gb=200, storage_free_gb=900, cpu_free_mhz=76_000))
    result = await capacity.summary()
    assert (result.ok, result.error) == (True, None)
    assert (result.cpu_total_ghz, result.cpu_free_ghz) == (100.0, 76.0)
    assert (result.ram_total_gb, result.ram_free_gb) == (512, 200)
    assert (result.storage_total_gb, result.storage_free_gb) == (2000, 900)


async def test_summary_without_vcenter(monkeypatch):
    monkeypatch.setattr(settings, "vcenter_host", "")
    result = await capacity.summary()
    assert (result.ok, result.error) == (False, "vCenter не подключён")


@pytest.mark.parametrize("error, text", [
    (VSphereError("Не найден кластер «X»"), "Не найден кластер «X»"),
    (RuntimeError("секрет в тексте исключения"), "Не удалось получить данные из vCenter"),
])
async def test_summary_vcenter_failure_is_reported_not_raised(vcenter, monkeypatch, error, text):
    def boom():
        raise error
    monkeypatch.setattr(vsphere_client, "cluster_usage", boom)
    result = await capacity.summary()
    assert (result.ok, result.error) == (False, text)  # текст чужого исключения наружу не уходит


async def test_cluster_endpoint_admin_only(client, login, api, make_user, vcenter, monkeypatch):
    monkeypatch.setattr(vsphere_client, "cluster_usage", lambda: usage())
    assert (await client.get(api("/admin/cluster"))).status_code == 401
    login(await make_user("worker"))
    assert (await client.get(api("/admin/cluster"))).status_code == 403
    login(await make_user("boss", role="admin"))
    r = await client.get(api("/admin/cluster"))
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["ram_free_gb"] == 100
