"""Воркер: изоляция ошибок шагов, восстановление очереди ВМ при старте, интервал синхронизации.
Шаги и sleep подменяются, реальных ожиданий нет; настройки читаются из тестовой БД."""
import asyncio
import logging
from types import SimpleNamespace

import pytest

from app import worker
from app.core.config import settings
from app.services import jira_closure, norms, overdue, runtime, service_requests, vm_jobs


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
    monkeypatch.setattr(vm_jobs, "create_pending", fake("vm-create"))
    monkeypatch.setattr(vm_jobs, "upkeep", fake("vm-upkeep"))
    monkeypatch.setattr(vm_jobs, "recover", fake("recover"))
    monkeypatch.setattr(service_requests, "refresh_open", fake("sd"))
    monkeypatch.setattr(jira_closure, "apply_closures", fake("closures"))
    monkeypatch.setattr(norms, "check", fake("norms"))
    monkeypatch.setattr(overdue, "daily_digest", fake("digest"))
    monkeypatch.setattr(overdue, "daily_reminders", fake("reminders"))
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
    assert calls == ["writeback", "sd", "closures", "norms", "digest", "reminders"]  # остальные шаги выполнены
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


async def test_slow_vm_step_does_not_block_insight_cycle(calls, monkeypatch):
    """Долгий клон ВМ идёт в своём цикле: синхронизация, запись в Insight и заявки не ждут его."""
    release = asyncio.Event()

    async def slow_create(session):
        await release.wait()

    monkeypatch.setattr(vm_jobs, "create_pending", slow_create)
    vm_task = asyncio.create_task(worker._step("Создание ВМ", vm_jobs.create_pending))
    await asyncio.sleep(0)  # ВМ-шаг начался и завис на ожидании
    await worker._tick(0.0, clock=Clock())
    assert calls == ["sync", "writeback", "sd", "closures", "norms", "digest", "reminders"] and not vm_task.done()
    release.set()
    await vm_task


class StopLoop(Exception):
    pass


@pytest.fixture
def slept(monkeypatch):
    """Подменяет asyncio в воркере: sleep записывает паузу и прерывает цикл, gather остаётся настоящим."""
    pauses: list[float] = []

    async def fake_sleep(sec):
        pauses.append(sec)
        raise StopLoop

    monkeypatch.setattr(worker, "asyncio", SimpleNamespace(sleep=fake_sleep, gather=asyncio.gather))
    return pauses


async def test_repeat_runs_step_then_pauses(slept):
    seen = []

    async def step(session):
        seen.append(session)

    with pytest.raises(StopLoop):
        await worker._repeat("шаг", step)
    assert len(seen) == 1 and slept == [worker.TICK_SEC]


async def test_repeat_survives_failing_step(slept, caplog):
    async def boom(session):
        raise RuntimeError("сбой")

    with caplog.at_level(logging.ERROR, logger="hmsrent.worker"), pytest.raises(StopLoop):
        await worker._repeat("Создание ВМ", boom)  # ошибка шага не мешает дойти до паузы и продолжить цикл
    assert "Создание ВМ упал" in caplog.text and slept == [worker.TICK_SEC]


async def test_insight_loop_does_one_tick_then_pauses(calls, slept):
    with pytest.raises(StopLoop):
        await worker._insight_loop()
    assert calls == ["sync", "writeback", "sd", "closures", "norms", "digest", "reminders"] and slept == [worker.TICK_SEC]


@pytest.fixture
def started(monkeypatch):
    """main() запускает циклы: вместо бесконечных — заглушки, записывающие, какие циклы стартовали."""
    log: list[str] = []

    async def insight_loop():
        log.append("insight")

    def repeat(name, step):
        async def loop():
            log.append(name)
        return loop()

    monkeypatch.setattr(worker, "_insight_loop", insight_loop)
    monkeypatch.setattr(worker, "_repeat", repeat)
    return log


async def test_main_recovers_and_starts_vm_loops_when_vsphere_configured(calls, started, monkeypatch):
    for key, value in (("vcenter_host", "vc.local"), ("vcenter_user", "svc"), ("vcenter_password", "pw")):
        monkeypatch.setattr(settings, key, value)
    await worker.main()
    assert calls == ["recover"]  # очередь восстановлена до запуска циклов
    assert set(started) == {"insight", "Создание ВМ", "Удаление ВМ"} and len(started) == 3


async def test_main_starts_only_insight_loop_without_vsphere(calls, started, monkeypatch):
    monkeypatch.setattr(settings, "vcenter_host", "")
    await worker.main()
    assert calls == [] and started == ["insight"]
