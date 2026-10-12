"""Фоновый воркер: периодическая синхронизация с Insight и обратная запись.

Запуск: python -m app.worker  (в docker-compose — отдельный сервис `worker`).
"""
import asyncio
import logging
import time

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.sync import run_sync
from app.services.writeback import push_pending

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hmsrent.worker")

WRITEBACK_INTERVAL_SEC = 30


async def main() -> None:
    log.info("Воркер запущен: insight=%s, интервал синхронизации %s с, writeback=%s",
             settings.insight_mode, settings.insight_sync_interval_sec, settings.insight_writeback)
    next_sync = 0.0
    while True:
        if time.monotonic() >= next_sync:
            try:
                async with SessionLocal() as session:
                    await run_sync(session)
            except Exception:  # noqa: BLE001 — воркер не должен падать из-за одной ошибки
                log.exception("Синхронизация упала")
            next_sync = time.monotonic() + settings.insight_sync_interval_sec
        try:
            async with SessionLocal() as session:
                pushed = await push_pending(session)
                if pushed:
                    log.info("Записано в Insight: %s ПК", pushed)
        except Exception:  # noqa: BLE001
            log.exception("Writeback упал")
        await asyncio.sleep(WRITEBACK_INTERVAL_SEC)


if __name__ == "__main__":
    asyncio.run(main())
