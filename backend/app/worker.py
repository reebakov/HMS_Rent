"""Фоновый воркер: синхронизация с Insight, запись в Insight, виртуалки в vSphere.

Три независимых цикла в одном процессе: Insight и заявки, создание ВМ, удаление ВМ. Клонирование ВМ длится до часа и
не должно останавливать синхронизацию и запись в Insight.

Запуск: python -m app.worker  (в docker-compose — отдельный сервис `worker`).
Интервал синхронизации и запись в Insight берутся из настроек на сайте (Админка → «Настройки»).
"""
import asyncio
import logging
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import jira_closure, norms, overdue, runtime, service_requests, vm_insight, vm_jobs
from app.services.sync import run_sync
from app.services.writeback import push_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hmsrent.worker")

TICK_SEC = 5  # как часто проверять очередь ВМ и запись в Insight (у каждого цикла своя пауза)


async def _step(name: str, coro_factory) -> None:
    try:
        async with SessionLocal() as session:
            await coro_factory(session)
    except Exception:  # воркер не должен падать из-за одной ошибки
        log.exception("%s упал", name)


async def _tick(next_sync: float, clock=time.monotonic) -> float:
    """Один проход цикла. Возвращает момент (по clock), когда нужна следующая синхронизация с Insight."""
    async with SessionLocal() as session:
        cfg = await runtime.load(session, max_age=0)
    if clock() >= next_sync:
        await _step("Синхронизация", run_sync)
        next_sync = clock() + cfg.insight_sync_interval_min * 60
    await _step("Запись в Insight", push_pending)
    await _step("Запись ВМ в Insight", vm_insight.push_pending)
    await _step("Заявки Service Desk", service_requests.refresh_open)
    await _step("Закрытия в Jira", jira_closure.apply_closures)
    await _step("Нормативы исполнителей", norms.check)
    await _step("Сводка просрочек", overdue.daily_digest)
    await _step("Напоминания о сроке", overdue.daily_reminders)
    return next_sync


async def _insight_loop() -> None:
    next_sync = 0.0
    while True:
        next_sync = await _tick(next_sync)
        await asyncio.sleep(TICK_SEC)


async def _repeat(name: str, step) -> None:
    while True:
        await _step(name, step)
        await asyncio.sleep(TICK_SEC)


async def main() -> None:
    log.info("Воркер запущен: insight=%s, vSphere=%s", settings.insight_mode,
             settings.vcenter_host if settings.vsphere_configured else "не настроен")
    loops = [_insight_loop()]
    if settings.vsphere_configured:
        await _step("Восстановление очереди ВМ", vm_jobs.recover)
        loops += [_repeat("Создание ВМ", vm_jobs.create_pending), _repeat("Удаление ВМ", vm_jobs.upkeep)]
    await asyncio.gather(*loops)


if __name__ == "__main__":
    asyncio.run(main())
