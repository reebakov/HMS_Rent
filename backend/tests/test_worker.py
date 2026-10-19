"""Воркер: изоляция ошибок шагов, восстановление очереди ВМ при старте, интервал синхронизации.
Шаги и sleep подменяются, реальных ожиданий нет; настройки читаются из тестовой БД."""
import logging
from types import SimpleNamespace

import pytest

from app import worker
from app.core.config import settings
from app.services import overdue, runtime, service_requests, vm_jobs


@pytest.fixture
def calls(monkeypatch):
    """Подменяет все шаги воркера на заглушки, пишущие своё имя в список."""
    log: list[str] = []

    def fake(name):
        async def step(session):
            log.append(name)
        return step

    monkeypatch.setattr(worker, "run_sync", fake("sync"))
    monkeypatch.setattr(worker, "push_pending", fake("writeback"))
    monkeypatch.setattr(vm_jobs, "run_once", fake("vm"))
    monkeypatch.setattr(vm_jobs, "recover", fake("recover"))
    monkeypatch.setattr(service_requests, "refresh_open", fake("sd"))
    monkeypatch.setattr(overdue, "daily_digest", fake("digest"))
    return log


class Clock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


async def test_step_swallows_error_and_logs_it(caplog):
    async def boom(session):
        raise RuntimeError("сбой шага")

    with caplog.at_level(logging.ERROR, logger="hmsrent.worker"):
        await worker._step("Тестовый шаг", boom)  # исключение не пробрасывается
    assert "Тестовый шаг упал" in caplog.text and "сбой шага" in caplog.text


async def test_step_passes_session_to_step():
    seen = []

    async def ok(session):
        seen.append(session)

    await worker._step("ok", ok)
    assert len(seen) == 1 and hasattr(seen[0], "execute")


async def test_failed_step_does_not_stop_next_steps(calls, monkeypatch, caplog):
    async def boom(session):
        raise RuntimeError("sync упал")

    monkeypatch.setattr(worker, "run_sync", boom)
    with caplog.at_level(logging.ERROR, logger="hmsrent.worker"):
        await worker._tick(0.0, clock=Clock())
    assert calls == ["writeback", "vm", "sd", "digest"]  # остальные шаги выполнены
    assert "Синхронизация упал" in caplog.text


async def test_tick_respects_sync_interval(calls, session):
    await runtime.put_setting(session, "insight_sync_interval_min", 3)
    await session.commit()
    clock = Clock()

    next_sync = await worker._tick(0.0, clock=clock)  # первый тик: синхронизация нужна сразу
    assert calls.count("sync") == 1 and next_sync == clock.now + 3 * 60

    clock.now += 3 * 60 - 1  # интервал ещё не прошёл
    assert await worker._tick(next_sync, clock=clock) == next_sync
    assert calls.count("sync") == 1
    assert calls.count("writeback") == 2  # остальные шаги выполняются на каждом тике

    clock.now += 1  # интервал прошёл
    next_sync = await worker._tick(next_sync, clock=clock)
    assert calls.count("sync") == 2 and next_sync == clock.now + 3 * 60


class StopLoop(Exception):
    pass


@pytest.fixture
def one_pass(monkeypatch):
    """main() делает один проход цикла и останавливается на первом sleep."""
    slept: list[float] = []

    async def fake_sleep(sec):
        slept.append(sec)
        raise StopLoop

    monkeypatch.setattr(worker, "asyncio", SimpleNamespace(sleep=fake_sleep))  # глобальный asyncio не трогаем
    return slept


async def test_main_recovers_vm_queue_when_vsphere_configured(calls, one_pass, monkeypatch):
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)
    with pytest.raises(StopLoop):
        await worker.main()
    assert calls[0] == "recover" and calls[1:] == ["sync", "writeback", "vm", "sd", "digest"]
    assert one_pass == [worker.TICK_SEC]


async def test_main_skips_recover_without_vsphere(calls, one_pass, monkeypatch):
    monkeypatch.setattr(settings, "vcenter_host", "")
    with pytest.raises(StopLoop):
        await worker.main()
    assert "recover" not in calls and calls[0] == "sync"
