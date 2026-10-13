"""Фоновый воркер: синхронизация с Insight, запись в Insight, виртуалки в vSphere.

Запуск: python -m app.worker  (в docker-compose — отдельный сервис `worker`).
Интервал синхронизации и запись в Insight берутся из настроек на сайте (Админка → «Настройки»).
"""
import asyncio
import logging
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services import runtime, vm_jobs
from app.services.sync import run_sync
from app.services.writeback import push_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hmsrent.worker")

TICK_SEC = 5  # как часто проверять очередь ВМ и запись в Insight


async def _step(name: str, coro_factory) -> None:
    try:
        async with SessionLocal() as session:
            await coro_factory(session)
    except Exception:  # noqa: BLE001 — воркер не должен падать из-за одной ошибки
        log.exception("%s упал", name)


async def main() -> None:
    log.info("Воркер запущен: insight=%s, vSphere=%s", settings.insight_mode,
             settings.vcenter_host if settings.vsphere_configured else "не настроен")
    if settings.vsphere_configured:
        await _step("Восстановление очереди ВМ", vm_jobs.recover)
    next_sync = 0.0
    while True:
        async with SessionLocal() as session:
            cfg = await runtime.load(session, max_age=0)
        if time.monotonic() >= next_sync:
            await _step("Синхронизация", run_sync)
            next_sync = time.monotonic() + cfg.insight_sync_interval_min * 60
        await _step("Запись в Insight", push_pending)
        await _step("Виртуалки", vm_jobs.run_once)
        await asyncio.sleep(TICK_SEC)


if __name__ == "__main__":
    asyncio.run(main())
